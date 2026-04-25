"""Claude Code hook integration.

Ships an optional hook that tags Claude sessions in the jarvis DB in real
time: SessionStart seeds repo/jarvis-involved tags, PostToolUse(Bash)
catches `gh pr create` and attaches a PR link tag, and SessionEnd refreshes
correlation for that session.

All settings changes are non-destructive: we merge into
~/.claude/settings.json and mark entries with a sentinel so we can detect
and cleanly remove them on uninstall.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

_SENTINEL_KEY = "_jarvis_managed"
_HOOK_COMMAND = "jarvis hooks handle"
_HOOK_EVENTS = ("SessionStart", "PostToolUse", "SessionEnd")


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


def _load_settings() -> dict[str, Any]:
    if not CLAUDE_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(CLAUDE_SETTINGS_PATH.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def _save_settings(data: dict[str, Any]) -> None:
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n")


def _hook_entry(matcher: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        _SENTINEL_KEY: True,
        "hooks": [{"type": "command", "command": _HOOK_COMMAND}],
    }
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def install_hooks() -> list[str]:
    """Install jarvis-managed Claude Code hooks. Returns a list of event names added."""
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    added: list[str] = []

    for event in _HOOK_EVENTS:
        bucket = hooks.setdefault(event, [])
        if any(_is_jarvis_entry(e) for e in bucket):
            continue
        if event == "PostToolUse":
            bucket.append(_hook_entry(matcher="Bash"))
        else:
            bucket.append(_hook_entry())
        added.append(event)

    _save_settings(settings)
    return added


def uninstall_hooks() -> list[str]:
    """Remove jarvis-managed hooks. Returns event names cleaned up."""
    settings = _load_settings()
    hooks = settings.get("hooks") or {}
    removed: list[str] = []
    for event in list(hooks.keys()):
        kept = [e for e in hooks[event] if not _is_jarvis_entry(e)]
        if len(kept) != len(hooks[event]):
            removed.append(event)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    _save_settings(settings)
    return removed


def _is_jarvis_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get(_SENTINEL_KEY):
        return True
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and hook.get("command", "").startswith("jarvis hooks handle"):
            return True
    return False


def status() -> dict[str, bool]:
    settings = _load_settings()
    hooks = settings.get("hooks") or {}
    return {
        event: any(_is_jarvis_entry(e) for e in (hooks.get(event) or [])) for event in _HOOK_EVENTS
    }


# ---------------------------------------------------------------------------
# Event handling (stdin JSON → DB)
# ---------------------------------------------------------------------------


_PR_URL_RE = re.compile(r"https?://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")


def _git_branch(cwd: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        return out if out != "HEAD" else ""
    except Exception:
        return ""


def resolve_gh_account_for_cwd(conn: Any, cwd: str) -> str | None:
    """Return the gh_account configured for whichever registered repo path
    contains this cwd. Longest match wins (handles nested repos). The hook
    re-reads this on every invocation, so UI changes to the mapping take
    effect on the next SessionStart — no reinstall needed.
    """
    from jarvis.db import list_repo_paths

    if not cwd:
        return None
    cwd_path = Path(cwd).expanduser().resolve()
    best: tuple[int, str | None] | None = None
    for row in list_repo_paths(conn):
        acct = row.get("gh_account")
        if not acct:
            continue
        try:
            p = Path(row["path"]).expanduser().resolve()
        except Exception:
            continue
        try:
            cwd_path.relative_to(p)
        except ValueError:
            continue
        depth = len(p.parts)
        if best is None or depth > best[0]:
            best = (depth, acct)
    return best[1] if best else None


def _handle_session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
    from jarvis.db import get_db
    from jarvis.sessions_tags import apply_patch

    session_id = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    if not session_id or not cwd:
        return None

    project = Path(cwd).name if cwd else None
    tags: list[str] = []
    if project:
        tags.append(f"repo:{project}")
    if project == "jarvis" or "/jarvis" in cwd:
        tags.append("jarvis-involved")
    branch = _git_branch(cwd)
    if branch:
        tags.append(f"branch:{branch}")

    conn = get_db()
    try:
        gh_account = resolve_gh_account_for_cwd(conn, cwd)
        if gh_account:
            tags.append(f"gh:{gh_account}")
        if tags:
            apply_patch(conn, session_id, add_tags=tags)
    finally:
        conn.close()

    if gh_account:
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    f"This repo is configured in Jarvis to use the GitHub account"
                    f" '{gh_account}'. For any `gh` commands in this session,"
                    f" prefix with `GH_TOKEN=$(gh auth token --user {gh_account})`"
                    f" so you act as that identity instead of the default one."
                ),
            }
        }
    return None


def _handle_post_tool_use(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    tool_output = payload.get("tool_output") or ""
    if isinstance(tool_output, dict):
        tool_output = tool_output.get("stdout", "") + "\n" + tool_output.get("stderr", "")
    if "gh pr create" not in command:
        return

    match = _PR_URL_RE.search(str(tool_output))
    if not match:
        return
    repo, number = match.group(1), int(match.group(2))
    session_id = payload.get("session_id") or ""
    if not session_id:
        return

    from jarvis.db import get_db
    from jarvis.sessions_tags import add_pr_link

    conn = get_db()
    add_pr_link(conn, session_id, repo, number)
    conn.close()


def _handle_session_end(payload: dict[str, Any]) -> dict[str, Any] | None:
    from jarvis.sessions_tags import correlate_claude_sessions

    correlate_claude_sessions()


_DISPATCH = {
    "SessionStart": _handle_session_start,
    "PostToolUse": _handle_post_tool_use,
    "SessionEnd": _handle_session_end,
}


def handle_stdin() -> int:
    """Entry point for `jarvis hooks handle`. Reads JSON on stdin, dispatches."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    event = payload.get("hook_event_name")
    handler = _DISPATCH.get(event)
    if handler is None:
        return 0
    try:
        result = handler(payload)
    except Exception:
        # Never block Claude Code on our bookkeeping failures.
        return 0
    if isinstance(result, dict):
        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
    return 0
