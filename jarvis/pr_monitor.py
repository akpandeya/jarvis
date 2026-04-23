"""PR monitor — polls open PRs across all configured GitHub accounts.

Fires deterministic signals (CI failure, review comments, auto-merge readiness,
staging deploy, oversized diff). LLM is called only for CI diagnosis and review
comment summaries; results are cached by content hash.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx
import keyring

from jarvis.brain import _call_claude
from jarvis.db import Suggestion, insert_activity, upsert_suggestion

API = "https://api.github.com"

_DEFAULT_MAX_FILES = 10
_DEFAULT_MAX_LINES = 500


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(url: str, token: str, params: dict | None = None) -> Any:
    try:
        r = httpx.get(url, headers=_headers(token), params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cache helpers (stored as activity_log rows with source='pr_monitor_cache')
# ---------------------------------------------------------------------------


def _cache_key(kind: str, content_hash: str) -> str:
    return f"{kind}:{content_hash}"


def _get_cache(conn: sqlite3.Connection, kind: str, content_hash: str) -> str | None:
    key = _cache_key(kind, content_hash)
    row = conn.execute(
        "SELECT body FROM activity_log WHERE source='pr_monitor_cache' AND title=? LIMIT 1",
        (key,),
    ).fetchone()
    return row["body"] if row else None


def _set_cache(conn: sqlite3.Connection, kind: str, content_hash: str, value: str) -> None:
    insert_activity(
        conn,
        source="pr_monitor_cache",
        kind=kind,
        happened_at=datetime.now(UTC),
        title=_cache_key(kind, content_hash),
        body=value,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Signal: CI failure
# ---------------------------------------------------------------------------


def _check_ci_failure(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    token: str,
) -> Suggestion | None:
    head_sha = pr.get("head", {}).get("sha")
    if not head_sha:
        return None

    check_runs = _get(f"{API}/repos/{repo}/commits/{head_sha}/check-runs", token)
    if not check_runs:
        return None

    failed = [r for r in check_runs.get("check_runs", []) if r.get("conclusion") == "failure"]
    if not failed:
        return None

    run = failed[0]
    run_id = run["id"]
    run_name = run["name"]
    pr_number = pr["number"]

    # Fetch the log
    log_text = ""
    jobs = _get(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs", token)
    if jobs:
        for job in jobs.get("jobs", []):
            if job.get("conclusion") == "failure":
                steps = job.get("steps", [])
                failed_steps = [s["name"] for s in steps if s.get("conclusion") == "failure"]
                log_text += f"Job: {job['name']}\nFailed steps: {', '.join(failed_steps)}\n"
                # Fetch log text
                log_url = job.get("logs_url") or f"{API}/repos/{repo}/actions/jobs/{job['id']}/logs"
                try:
                    log_resp = httpx.get(
                        log_url, headers=_headers(token), timeout=15, follow_redirects=True
                    )
                    # Truncate — last 3000 chars most relevant
                    log_text += log_resp.text[-3000:]
                except Exception:
                    pass
                break

    content_hash = _sha(log_text or run_name)
    cached = _get_cache(conn, "ci_diagnosis", content_hash)

    if cached:
        diagnosis = cached
    else:
        if log_text:
            diagnosis = _call_claude(
                "You are a CI debugging assistant. Given a failing CI job log, explain in "
                "2-3 sentences what went wrong and suggest the most likely fix. Be specific "
                "— reference file names, test names, or error messages. "
                "Format: **Root cause:** ... **Suggested fix:** ...",
                f"PR #{pr_number} — failing check: {run_name}\n\n{log_text}",
            )
        else:
            diagnosis = f"Check '{run_name}' failed. Fetch logs manually for details."
        _set_cache(conn, "ci_diagnosis", content_hash, diagnosis)

    return Suggestion(
        rule_id=f"ci_failure_pr{pr_number}",
        message=f"CI failing on PR #{pr_number} ({pr['title'][:60]}): {run_name}\n{diagnosis}",
        action=f"jarvis pr-fix {pr_number}",
        priority=90,
    )


# ---------------------------------------------------------------------------
# Signal: review comments
# ---------------------------------------------------------------------------


def _check_review_comments(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    token: str,
) -> Suggestion | None:
    pr_number = pr["number"]
    comments = _get(f"{API}/repos/{repo}/pulls/{pr_number}/comments", token)
    if not comments:
        return None

    # Only new comments (last 24h)
    cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    new_comments = [
        c
        for c in comments
        if datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")) >= cutoff
    ]
    if not new_comments:
        return None

    comment_text = "\n\n".join(
        f"**{c['user']['login']}** on `{c.get('path', '')}` line {c.get('line', '?')}:\n{c['body']}"
        for c in new_comments[:10]
    )
    content_hash = _sha(comment_text)
    cached = _get_cache(conn, "review_summary", content_hash)

    if cached:
        summary = cached
    else:
        summary = _call_claude(
            "Summarise these pull request review comments in 2-3 sentences. "
            "Focus on the main concerns and what changes are needed.",
            f"PR #{pr_number} — {pr['title']}\n\n{comment_text}",
        )
        _set_cache(conn, "review_summary", content_hash, summary)

    return Suggestion(
        rule_id=f"review_comments_pr{pr_number}",
        message=f"New review comments on PR #{pr_number}: {summary}",
        action=f"gh pr view {pr_number} --web",
        priority=80,
    )


# ---------------------------------------------------------------------------
# Signal: ready to merge
# ---------------------------------------------------------------------------


def _check_ready_to_merge(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    token: str,
) -> Suggestion | None:
    pr_number = pr["number"]
    if pr.get("draft"):
        return None

    # Check review state
    reviews = _get(f"{API}/repos/{repo}/pulls/{pr_number}/reviews", token)
    if not reviews:
        return None

    # Latest review per user
    latest: dict[str, str] = {}
    for r in reviews:
        latest[r["user"]["login"]] = r["state"]

    approved = all(s == "APPROVED" for s in latest.values()) and latest
    if not approved:
        return None

    # Check CI
    head_sha = pr.get("head", {}).get("sha")
    if head_sha:
        check_runs = _get(f"{API}/repos/{repo}/commits/{head_sha}/check-runs", token)
        if check_runs:
            conclusions = [r.get("conclusion") for r in check_runs.get("check_runs", [])]
            if any(c == "failure" for c in conclusions):
                return None
            if any(c is None for c in conclusions):
                return None  # still running

    return Suggestion(
        rule_id=f"ready_to_merge_pr{pr_number}",
        message=f"PR #{pr_number} is approved and CI is green — ready to merge",
        action=f"gh pr merge {pr_number} --merge",
        priority=85,
    )


# ---------------------------------------------------------------------------
# Signal: oversized PR
# ---------------------------------------------------------------------------


def _check_pr_size(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    token: str,
    max_files: int = _DEFAULT_MAX_FILES,
    max_lines: int = _DEFAULT_MAX_LINES,
) -> Suggestion | None:
    pr_number = pr["number"]
    changed_files = pr.get("changed_files", 0)
    additions = pr.get("additions", 0)
    deletions = pr.get("deletions", 0)
    total_lines = additions + deletions

    if changed_files <= max_files and total_lines <= max_lines:
        return None

    # Fetch diff for LLM analysis
    try:
        diff_resp = httpx.get(
            f"{API}/repos/{repo}/pulls/{pr_number}",
            headers={**_headers(token), "Accept": "application/vnd.github.v3.diff"},
            timeout=20,
        )
        diff_text = diff_resp.text[:4000]
    except Exception:
        diff_text = f"{changed_files} files changed, +{additions}/-{deletions} lines"

    content_hash = _sha(diff_text)
    cached = _get_cache(conn, "pr_size", content_hash)

    if cached:
        plan = cached
    else:
        plan = _call_claude(
            "This pull request is too large to review effectively. "
            "Analyse the diff and suggest a concrete plan to split it into smaller, "
            "independently-mergeable PRs or a stacked PR series. "
            "Be specific about which files/changes belong in each part.",
            (
                f"PR #{pr_number}: {pr['title']}\n"
                f"{changed_files} files, +{additions}/-{deletions} lines\n\n{diff_text}"
            ),
        )
        _set_cache(conn, "pr_size", content_hash, plan)

    return Suggestion(
        rule_id=f"pr_too_large_{pr_number}",
        message=(
            f"PR #{pr_number} is large ({changed_files} files, {total_lines} lines): {plan[:200]}"
        ),
        action=f"gh pr view {pr_number} --web",
        priority=60,
    )


# ---------------------------------------------------------------------------
# Signal: staging deploy → promote to production
# ---------------------------------------------------------------------------


def _check_staging_deploy(
    conn: sqlite3.Connection,
    repo: str,
    pr: dict,
    token: str,
    staging_patterns: list[str] | None = None,
) -> Suggestion | None:
    pr_number = pr["number"]
    patterns = staging_patterns or ["staging", "stg", "stage"]

    deployments = _get(
        f"{API}/repos/{repo}/deployments",
        token,
        params={"sha": pr.get("head", {}).get("sha"), "per_page": 10},
    )
    if not deployments:
        return None

    for dep in deployments:
        env = dep.get("environment", "").lower()
        if not any(p in env for p in patterns):
            continue

        # Check already-promoted flag via cache
        dep_id = dep["id"]
        if _get_cache(conn, "staging_promoted", str(dep_id)):
            return None

        return Suggestion(
            rule_id=f"staging_deploy_pr{pr_number}",
            message=(
                f"PR #{pr_number} is deployed to staging ({dep.get('environment')})"
                " — promote to production?"
            ),
            action=f"gh workflow run deploy.yml --field pr={pr_number} --field env=production",
            priority=75,
        )

    return None


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------


def run_monitor(
    conn: sqlite3.Connection,
    account_keys: list[str] | None = None,
    repos: list[str] | None = None,
    max_files: int = _DEFAULT_MAX_FILES,
    max_lines: int = _DEFAULT_MAX_LINES,
    staging_patterns: list[str] | None = None,
) -> dict[str, int]:
    """Poll open PRs and upsert suggestions. Returns signal counts."""
    keys = account_keys or ["github_token"]
    counts: dict[str, int] = {
        "prs_checked": 0,
        "ci_failures": 0,
        "review_comments": 0,
        "ready_to_merge": 0,
        "oversized": 0,
        "staging_deploys": 0,
    }

    for key in keys:
        token = keyring.get_password("jarvis", key)
        if not token:
            continue

        # Discover repos from open PRs if not specified
        target_repos = repos or []
        if not target_repos:
            # Fall back to repos from config
            from jarvis.config import JarvisConfig

            cfg = JarvisConfig.load()
            target_repos = cfg.github.repos

        for repo in target_repos:
            prs = _get(
                f"{API}/repos/{repo}/pulls",
                token,
                params={"state": "open", "per_page": 30},
            )
            if not prs:
                continue

            for pr in prs:
                counts["prs_checked"] += 1

                for signal_fn, count_key in [
                    (lambda c, r, p, t: _check_ci_failure(c, r, p, t), "ci_failures"),
                    (lambda c, r, p, t: _check_review_comments(c, r, p, t), "review_comments"),
                    (lambda c, r, p, t: _check_ready_to_merge(c, r, p, t), "ready_to_merge"),
                    (
                        lambda c, r, p, t: _check_pr_size(c, r, p, t, max_files, max_lines),
                        "oversized",
                    ),
                    (
                        lambda c, r, p, t: _check_staging_deploy(c, r, p, t, staging_patterns),
                        "staging_deploys",
                    ),
                ]:
                    try:
                        suggestion = signal_fn(conn, repo, pr, token)
                        if suggestion:
                            upsert_suggestion(conn, suggestion)
                            counts[count_key] += 1
                    except Exception:
                        pass

    # Record activity
    insert_activity(
        conn,
        source="pr_monitor",
        kind="monitor_run",
        happened_at=datetime.now(UTC),
        title="PR monitor run",
        metadata=counts,
    )

    return counts


def list_open_prs(
    account_keys: list[str] | None = None,
    repos: list[str] | None = None,
) -> list[dict]:
    """Return a flat list of open PRs across all configured accounts."""
    from jarvis.config import JarvisConfig

    keys = account_keys or ["github_token"]
    cfg = JarvisConfig.load()
    target_repos = repos or cfg.github.repos
    result = []

    for key in keys:
        token = keyring.get_password("jarvis", key)
        if not token:
            continue
        for repo in target_repos:
            prs = _get(
                f"{API}/repos/{repo}/pulls",
                token,
                params={"state": "open", "per_page": 50},
            )
            if not prs:
                continue
            for pr in prs:
                head_sha = pr.get("head", {}).get("sha", "")
                # Get CI status
                ci_status = "unknown"
                check_runs = _get(f"{API}/repos/{repo}/commits/{head_sha}/check-runs", token)
                if check_runs:
                    conclusions = [r.get("conclusion") for r in check_runs.get("check_runs", [])]
                    if any(c == "failure" for c in conclusions):
                        ci_status = "failing"
                    elif all(c == "success" for c in conclusions if c):
                        ci_status = "passing"
                    else:
                        ci_status = "pending"

                result.append(
                    {
                        "repo": repo,
                        "number": pr["number"],
                        "title": pr["title"],
                        "author": pr["user"]["login"],
                        "draft": pr.get("draft", False),
                        "ci": ci_status,
                        "url": pr["html_url"],
                        "changed_files": pr.get("changed_files", 0),
                        "additions": pr.get("additions", 0),
                        "deletions": pr.get("deletions", 0),
                    }
                )

    return result
