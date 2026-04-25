"""Claude Code sessions integration.

Reads all ~/.claude/projects/**/*.jsonl files and surfaces each conversation
as a single event. Covers sessions started in any project on this machine,
not just ones tracked through jarvis session save.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent

_CLAUDE_DIR = Path.home() / ".claude" / "projects"


def _decode_project_name(dir_name: str) -> str:
    """Convert '-Users-avanindra-pandeya-code-personal-jarvis' → 'jarvis'."""
    # Last path component is the project name
    parts = dir_name.lstrip("-").split("-")
    # Reconstruct path segments: runs of parts that form a real path
    # Simplest heuristic: last non-empty segment after splitting on known prefixes
    path = "/" + "/".join(parts)
    return Path(path).name or dir_name


def _first_text(content: object) -> str:
    """Extract first text string from a message content field (str or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
            if isinstance(block, str):
                return block
    return ""


def _parse_session(jsonl_path: Path, since: datetime) -> RawEvent | None:
    first_user_msg: str = ""
    first_assistant_msg: str = ""
    started_at: datetime | None = None
    last_message_at: datetime | None = None
    slug: str = ""
    git_branch: str = ""
    cwd: str = ""
    session_id: str = jsonl_path.stem
    turn_count = 0

    try:
        with open(jsonl_path, encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                if entry_type == "user" and not entry.get("isSidechain"):
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                        if started_at is None:
                            started_at = ts
                            slug = entry.get("slug", "")
                            git_branch = entry.get("gitBranch", "")
                            cwd = entry.get("cwd", "")
                            content = entry.get("message", {}).get("content", "")
                            first_user_msg = _first_text(content)
                        last_message_at = ts
                    turn_count += 1

                elif entry_type == "assistant" and not entry.get("isSidechain"):
                    if not first_assistant_msg:
                        content = entry.get("message", {}).get("content", "")
                        first_assistant_msg = _first_text(content)
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            last_message_at = ts
                        except ValueError:
                            pass
                    turn_count += 1

    except OSError:
        return None

    if started_at is None or not first_user_msg:
        return None

    # Normalise to UTC-aware
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    if started_at < since:
        return None

    project_name = _decode_project_name(jsonl_path.parent.name)
    title = f"[{project_name}] {first_user_msg[:100]}"

    return RawEvent(
        source="claude_sessions",
        kind="session",
        title=title,
        happened_at=started_at,
        body=first_assistant_msg[:500] or None,
        url=f"claude-session://{session_id}",
        project=project_name,
        metadata={
            "session_id": session_id,
            "slug": slug,
            "turns": turn_count,
            "branch": git_branch,
            "cwd": cwd,
            "last_message_at": last_message_at.isoformat() if last_message_at else None,
        },
    )


class ClaudeSessions:
    name = "claude_sessions"

    def health_check(self) -> bool:
        return _CLAUDE_DIR.exists()

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        if not _CLAUDE_DIR.exists():
            return []
        events = []
        for jsonl in _CLAUDE_DIR.glob("**/*.jsonl"):
            if "subagents" in jsonl.parts:
                continue
            event = _parse_session(jsonl, since)
            if event:
                events.append(event)
        return events
