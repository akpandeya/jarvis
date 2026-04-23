"""PR monitor — polls open PRs across all configured GitHub repos.

Uses the `gh` CLI for all GitHub operations — already authenticated, no token
management needed. LLM calls are cached by run_id / comment_hash so the same
failure or review set never triggers a second call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from typing import Any

from jarvis.brain import _call_claude
from jarvis.db import Suggestion, kv_get, kv_set, upsert_suggestion

log = logging.getLogger(__name__)

_CI_CACHE_PREFIX = "pr_ci_explained"
_COMMENTS_CACHE_PREFIX = "pr_comments_hash"


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------


def _gh(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a gh CLI command and return the CompletedProcess."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _gh_json(*args: str) -> Any:
    """Run a gh CLI command that returns JSON. Returns None on failure."""
    result = _gh(*args)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Cache helpers (backed by kv store)
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _ci_cache_key(run_id: str) -> str:
    return f"{_CI_CACHE_PREFIX}:{run_id}"


def _comments_cache_key(pr_number: int) -> str:
    return f"{_COMMENTS_CACHE_PREFIX}:{pr_number}"


# ---------------------------------------------------------------------------
# Signal: CI failure explanation (F2)
# ---------------------------------------------------------------------------


def _explain_ci_failure(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
) -> None:
    """Fetch failing CI log, explain with LLM, post comment on PR (once per run_id)."""
    pr_number = pr["number"]
    status_rollup = pr.get("statusCheckRollup") or []

    # Find the first failing run
    failing_run_id: str | None = None
    for check in status_rollup:
        if check.get("__typename") == "CheckRun" and check.get("status") == "COMPLETED":
            conclusion = check.get("conclusion", "")
            if conclusion in ("FAILURE", "TIMED_OUT", "STARTUP_FAILURE"):
                failing_run_id = str(check.get("databaseId", ""))
                break

    if not failing_run_id:
        return

    cache_key = _ci_cache_key(failing_run_id)
    if kv_get(conn, cache_key):
        # Already explained this run — skip
        return

    # Fetch the failing log via gh
    log_result = _gh("run", "view", failing_run_id, "--log-failed", "--repo", repo)
    log_text = (log_result.stdout or "")[:3000]

    prompt = f"Explain this CI failure in 3 bullets and suggest a fix:\n\n{log_text}"
    try:
        explanation = _call_claude(
            "You are a CI debugging assistant. Be concise and specific.",
            prompt,
        )
    except Exception as exc:
        explanation = f"(LLM unavailable: {exc})"

    # Post comment on the PR
    comment_body = f"**CI Failure — Automated Analysis**\n\n{explanation}"
    _gh(
        "pr",
        "comment",
        str(pr_number),
        "--repo",
        repo,
        "--body",
        comment_body,
    )

    # Cache so we never re-comment for this run_id
    kv_set(conn, cache_key, explanation)

    # Surface as a suggestion too
    upsert_suggestion(
        conn,
        Suggestion(
            rule_id=f"ci_failure_pr{pr_number}",
            message=(
                f"CI failing on PR #{pr_number} ({pr.get('title', '')[:60]}): {explanation[:200]}"
            ),
            action=f"gh pr view {pr_number} --repo {repo} --web",
            priority=90,
        ),
    )


# ---------------------------------------------------------------------------
# Signal: review comment summary (F3)
# ---------------------------------------------------------------------------


def _summarise_review_comments(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
) -> None:
    """Summarise new review comments with LLM and store as a suggestion (cached per hash)."""
    pr_number = pr["number"]
    comments_data = _gh_json("api", f"repos/{repo}/pulls/{pr_number}/comments")
    if not comments_data:
        return

    if not isinstance(comments_data, list) or len(comments_data) == 0:
        return

    comment_text = "\n\n".join(
        f"{c.get('user', {}).get('login', '?')} on {c.get('path', '?')}:\n{c.get('body', '')}"
        for c in comments_data[:10]
    )
    content_hash = _sha(comment_text)
    cache_key = _comments_cache_key(pr_number)

    existing = kv_get(conn, cache_key)
    if existing == content_hash:
        # Same comments as last check — nothing new
        return

    try:
        summary = _call_claude(
            "Summarise these pull request review comments in 2-3 sentences. "
            "Focus on the main concerns and what changes are needed.",
            f"PR #{pr_number} — {pr.get('title', '')}\n\n{comment_text}",
        )
    except Exception as exc:
        summary = f"(LLM unavailable: {exc})"

    kv_set(conn, cache_key, content_hash)

    upsert_suggestion(
        conn,
        Suggestion(
            rule_id=f"review_comments_pr{pr_number}",
            message=f"New review comments on PR #{pr_number}: {summary}",
            action=f"gh pr view {pr_number} --repo {repo} --web",
            priority=80,
        ),
    )


# ---------------------------------------------------------------------------
# Signal: auto-merge (F4)
# ---------------------------------------------------------------------------


def _maybe_automerge(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
) -> bool:
    """Auto-merge PR if approved and all checks green. Returns True if merged."""
    if pr.get("isDraft"):
        return False

    review_decision = pr.get("reviewDecision", "")
    if review_decision != "APPROVED":
        return False

    # Check CI — all checks must be success
    status_rollup = pr.get("statusCheckRollup") or []
    if not status_rollup:
        return False  # no checks at all — don't auto-merge

    for check in status_rollup:
        conclusion = check.get("conclusion", "")
        status = check.get("status", "")
        # Still running or failed
        if status != "COMPLETED" or conclusion not in ("SUCCESS", "SKIPPED", "NEUTRAL"):
            return False

    pr_number = pr["number"]
    result = _gh("pr", "merge", str(pr_number), "--repo", repo, "--squash", "--auto")
    if result.returncode == 0:
        log.info("Auto-merged PR #%s in %s", pr_number, repo)
        return True
    return False


# ---------------------------------------------------------------------------
# Signal: oversized PR (F5 — deterministic, no LLM)
# ---------------------------------------------------------------------------


def _check_pr_size(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    max_files: int = 20,
) -> None:
    """Flag PRs with too many changed files (deterministic — no LLM)."""
    pr_number = pr["number"]
    # changedFiles comes from the gh pr list JSON field
    changed_files = pr.get("changedFiles") or pr.get("changed_files") or 0

    if changed_files <= max_files:
        return

    upsert_suggestion(
        conn,
        Suggestion(
            rule_id=f"pr_too_large_{pr_number}",
            message=(
                f"PR #{pr_number} has {changed_files} changed files (>{max_files}). "
                "Consider splitting into smaller PRs."
            ),
            action=f"gh pr view {pr_number} --repo {repo} --web",
            priority=60,
        ),
    )


# ---------------------------------------------------------------------------
# Main monitor entry point
# ---------------------------------------------------------------------------


def run_pr_monitor() -> None:
    """Poll open PRs across all configured repos and surface suggestions.

    This is the callable target for `jarvis pr-monitor` and the launchd agent.
    """
    import keyring as kr

    from jarvis.config import JarvisConfig
    from jarvis.db import get_db

    # F9: exit cleanly if no GitHub token configured
    token = kr.get_password("jarvis", "github_token")
    if not token:
        log.warning(
            "GitHub token not configured — skipping PR monitor. "
            "Run `jarvis install` to set up credentials."
        )
        return

    if not shutil.which("gh"):
        log.warning("gh CLI not found — install GitHub CLI to use PR monitor.")
        return

    cfg = JarvisConfig.load()
    repos = cfg.github.repos
    if not repos:
        log.info("No repos configured in config.github.repos — nothing to check.")
        return

    conn = get_db()
    try:
        _run_monitor(conn, repos)
        # F6: record last check timestamp
        kv_set(conn, "last_pr_check_at", datetime.now(UTC).isoformat())
    finally:
        conn.close()


def _run_monitor(conn: sqlite3.Connection, repos: list[str]) -> None:
    """Inner loop — separated for testability."""
    for repo in repos:
        # gh pr list with the fields we need
        prs = _gh_json(
            "pr",
            "list",
            "--repo",
            repo,
            "--json",
            "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,changedFiles",
            "--state",
            "open",
        )
        if not prs:
            continue

        for pr in prs:
            try:
                _explain_ci_failure(conn, repo, pr)
            except Exception:
                log.exception("CI failure check failed for PR #%s in %s", pr.get("number"), repo)

            try:
                _summarise_review_comments(conn, repo, pr)
            except Exception:
                log.exception(
                    "Review comment check failed for PR #%s in %s", pr.get("number"), repo
                )

            try:
                _maybe_automerge(conn, repo, pr)
            except Exception:
                log.exception("Auto-merge check failed for PR #%s in %s", pr.get("number"), repo)

            try:
                _check_pr_size(conn, repo, pr)
            except Exception:
                log.exception("Size check failed for PR #%s in %s", pr.get("number"), repo)
