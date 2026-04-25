"""One-shot backfill that mines ~/.claude/projects/**/*.jsonl for PR URLs
created via `gh pr create`, and tags the corresponding Jarvis session.

Motivation: the real-time PostToolUse hook only catches PRs created after
the hook was installed. Old sessions still have the PR URLs in their jsonl
transcripts — we just need to walk them once.

Idempotent by virtue of `add_pr_link`, which dedupes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from jarvis.db import get_db
from jarvis.integrations.claude_sessions import _CLAUDE_DIR
from jarvis.sessions_tags import add_pr_link

# Match "gh pr create" at a shell-command boundary: start of string, after a
# shell separator (`&&`, `||`, `;`, `|`), or inside a `$(` / `` ` `` subshell.
# This avoids false positives when `gh pr create` appears inside a grep
# or awk pattern argument.
_GH_PR_CREATE_RE = re.compile(r"(?:^|[\s(`]|&&|\|\||;|\|)gh\s+pr\s+create\b")

_PR_URL_RE = re.compile(r"https?://github\.com/([^/\s]+/[^/\s]+?)/pull/(\d+)\b")


def _is_real_gh_pr_create(command: str) -> bool:
    return bool(_GH_PR_CREATE_RE.search(command or ""))


def _tool_result_text(block: dict[str, Any], envelope: dict[str, Any]) -> str:
    """Collect every text snippet that might contain the PR URL.

    Newer Claude Code builds store structured stdout/stderr under
    `toolUseResult` on the envelope, while the inline `content` block may be
    a string or a list of `{type: text, text}` parts.
    """
    parts: list[str] = []
    tur = envelope.get("toolUseResult")
    if isinstance(tur, dict):
        for key in ("stdout", "stderr", "output"):
            v = tur.get(key)
            if isinstance(v, str):
                parts.append(v)
    elif isinstance(tur, str):
        parts.append(tur)
    content = block.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "\n".join(parts)


def _extract_pr_urls(text: str) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for m in _PR_URL_RE.finditer(text):
        repo, number = m.group(1), int(m.group(2))
        key = (repo, number)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def scan_file(path: Path) -> list[tuple[str, str, int]]:
    """Return (session_id, repo, pr_number) triples found in this jsonl."""
    session_id = path.stem
    # First pass: collect Bash tool_use_ids for commands that really run
    # `gh pr create`.
    gh_pr_create_ids: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    parsed: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    for entry in parsed:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message") or {}
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Bash":
                continue
            cmd = (block.get("input") or {}).get("command") or ""
            if _is_real_gh_pr_create(cmd):
                tid = block.get("id")
                if tid:
                    gh_pr_create_ids.add(tid)

    if not gh_pr_create_ids:
        return []

    # Second pass: find matching tool_results and extract PR URLs.
    results: list[tuple[str, str, int]] = []
    for entry in parsed:
        if entry.get("type") != "user":
            continue
        msg = entry.get("message") or {}
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") not in gh_pr_create_ids:
                continue
            text = _tool_result_text(block, entry)
            for repo, number in _extract_pr_urls(text):
                results.append((session_id, repo, number))
    return results


def run_backfill(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Walk all Claude jsonl transcripts and add missing pr: tags + pr_links.

    Returns a summary dict: {files_scanned, sessions_touched, links_added}.
    """
    close = False
    if conn is None:
        conn = get_db()
        close = True

    files = 0
    sessions: set[str] = set()
    links = 0

    if not _CLAUDE_DIR.exists():
        if close:
            conn.close()
        return {"files_scanned": 0, "sessions_touched": 0, "links_added": 0}

    for jsonl in _CLAUDE_DIR.glob("**/*.jsonl"):
        if "subagents" in jsonl.parts:
            continue
        files += 1
        for session_id, repo, number in scan_file(jsonl):
            if add_pr_link(conn, session_id, repo, number):
                links += 1
                sessions.add(session_id)

    if close:
        conn.close()

    return {
        "files_scanned": files,
        "sessions_touched": len(sessions),
        "links_added": links,
    }
