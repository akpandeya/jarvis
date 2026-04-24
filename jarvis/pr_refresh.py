"""Shared helper for refreshing cached GitHub state on watched PRs.

Used by `jarvis/web/app.py` for the refresh-all and refresh-running HTTP
endpoints, and by `jarvis/cli.py` for the `jarvis pr refresh-watching`
CLI command (itself invoked by the launchd schedule-pr-refresh job).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

from jarvis.db import list_repo_paths, set_pr_watch_state, update_pr_cache

log = logging.getLogger(__name__)


def _gh(*args: str, repo: str | None = None, env: dict | None = None) -> dict | list | None:
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _remote_for_local_repo(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        m = re.search(r"github\.com[^:/]*[:/](.+?)(?:\.git)?$", url)
        return m.group(1) if m else None
    except Exception:
        return None


def _gh_token(account: str) -> str | None:
    try:
        r = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def token_for_repo(conn, repo: str) -> str | None:
    for row in list_repo_paths(conn):
        path = str(Path(row["path"]).expanduser())
        if _remote_for_local_repo(path) == repo and row.get("gh_account"):
            return _gh_token(row["gh_account"])
    return None


def parse_ci_status(pr_data: dict) -> str | None:
    rollup = pr_data.get("statusCheckRollup") or []
    if not rollup:
        return None
    statuses = {r.get("conclusion") or r.get("status") for r in rollup}
    if "FAILURE" in statuses or "failure" in statuses:
        return "failed"
    if all(s in ("SUCCESS", "success", "NEUTRAL", "SKIPPED") for s in statuses if s):
        return "passed"
    return "running"


def refresh_one(conn, sub: dict) -> bool:
    """Fetch live GitHub state for a single subscription and update the cache.

    Returns True if the PR was successfully fetched (and cache updated), False if
    the gh call failed. Auto-dismisses merged/closed PRs as a side effect.
    """
    repo = sub["repo"]
    pr_number = sub["pr_number"]
    token = token_for_repo(conn, repo)
    env = {**os.environ, "GH_TOKEN": token} if token else None
    data = _gh(
        "pr",
        "view",
        str(pr_number),
        "--json",
        "title,number,headRefName,url,author,reviewDecision,statusCheckRollup,state",
        repo=repo,
        env=env,
    )
    if not data:
        return False
    ci = parse_ci_status(data)
    rd = data.get("reviewDecision") or ""
    update_pr_cache(
        conn,
        repo,
        pr_number,
        ci,
        rd,
        title=data.get("title"),
        author=(data.get("author") or {}).get("login"),
        branch=data.get("headRefName"),
        pr_url=data.get("url"),
        state=(data.get("state") or "").lower() or None,
    )
    if (data.get("state") or "").lower() in ("merged", "closed"):
        set_pr_watch_state(conn, repo, pr_number, "dismissed")
    return True
