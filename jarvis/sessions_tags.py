"""Claude session tagging and overrides.

Stores user-facing state (display_title, archived, manual tags) and
auto-derived state (auto_tags, pr_links) in claude_session_overrides. This
table lives *outside* events.metadata because claude_sessions re-ingests
from jsonl and rewrites metadata on every run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from jarvis.db import get_db


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_row(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM claude_session_overrides WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def _parse_list(value: str | None) -> list:
    if not value:
        return []
    try:
        out = json.loads(value)
        return out if isinstance(out, list) else []
    except json.JSONDecodeError:
        return []


def effective_tags(row: dict[str, Any] | None) -> list[str]:
    if not row:
        return []
    auto = _parse_list(row.get("auto_tags"))
    manual = _parse_list(row.get("manual_tags"))
    removed = set(_parse_list(row.get("removed_tags")))
    seen: set[str] = set()
    out: list[str] = []
    for t in list(auto) + list(manual):
        if t in removed or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def get_overrides_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM claude_session_overrides").fetchall()
    return {r["session_id"]: dict(r) for r in rows}


def _upsert(conn: sqlite3.Connection, session_id: str, **fields: Any) -> None:
    existing = _load_row(conn, session_id)
    if existing is None:
        cols = ["session_id", "updated_at"] + list(fields.keys())
        vals = [session_id, _now()] + [fields[k] for k in fields]
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            f"INSERT INTO claude_session_overrides ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
    else:
        set_sql = ",".join(f"{k}=?" for k in fields) + ",updated_at=?"
        conn.execute(
            f"UPDATE claude_session_overrides SET {set_sql} WHERE session_id=?",
            list(fields.values()) + [_now(), session_id],
        )
    conn.commit()


def apply_patch(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    display_title: str | None = None,
    archived: bool | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    clear_display_title: bool = False,
) -> dict[str, Any]:
    existing = _load_row(conn, session_id) or {}
    manual = _parse_list(existing.get("manual_tags"))
    removed = _parse_list(existing.get("removed_tags"))
    auto = _parse_list(existing.get("auto_tags"))

    fields: dict[str, Any] = {}
    if clear_display_title:
        fields["display_title"] = None
    elif display_title is not None:
        fields["display_title"] = display_title.strip() or None
    if archived is not None:
        fields["archived"] = 1 if archived else 0

    if add_tags:
        for tag in add_tags:
            t = tag.strip()
            if not t:
                continue
            if t in removed:
                removed.remove(t)
            if t not in manual and t not in auto:
                manual.append(t)
            elif t in auto and t in removed:
                # re-adding an auto tag that had been removed
                pass
    if remove_tags:
        for tag in remove_tags:
            t = tag.strip()
            if not t:
                continue
            if t in manual:
                manual.remove(t)
            if t in auto and t not in removed:
                removed.append(t)

    if add_tags or remove_tags:
        fields["manual_tags"] = json.dumps(manual)
        fields["removed_tags"] = json.dumps(removed)

    if fields:
        _upsert(conn, session_id, **fields)
    return _load_row(conn, session_id) or {}


def set_auto(
    conn: sqlite3.Connection,
    session_id: str,
    auto_tags: list[str],
    pr_links: list[dict[str, Any]],
) -> None:
    _upsert(
        conn,
        session_id,
        auto_tags=json.dumps(auto_tags),
        pr_links=json.dumps(pr_links),
    )


# ---------------------------------------------------------------------------
# Correlator
# ---------------------------------------------------------------------------


_JARVIS_PROJECT_NAME = "jarvis"


def _derive_auto_tags(
    session_id: str,
    project: str | None,
    cwd: str | None,
    branch: str | None,
    pr_rows_by_branch: dict[str, list[sqlite3.Row]],
    pr_rows_by_session: dict[str, list[sqlite3.Row]],
) -> tuple[list[str], list[dict[str, Any]]]:
    tags: list[str] = []
    pr_links: list[dict[str, Any]] = []

    if project:
        tags.append(f"repo:{project}")
    if (project and project == _JARVIS_PROJECT_NAME) or (cwd and "/jarvis" in cwd):
        if "jarvis-involved" not in tags:
            tags.append("jarvis-involved")

    pr_rows: list[sqlite3.Row] = []
    if branch and branch in pr_rows_by_branch:
        pr_rows.extend(pr_rows_by_branch[branch])
    if session_id and session_id in pr_rows_by_session:
        pr_rows.extend(pr_rows_by_session[session_id])

    seen: set[tuple[str, int]] = set()
    for row in pr_rows:
        key = (row["repo"], int(row["pr_number"]))
        if key in seen:
            continue
        seen.add(key)
        pr_links.append({"repo": row["repo"], "number": int(row["pr_number"])})
        tag = f"pr:{row['repo']}#{row['pr_number']}"
        if tag not in tags:
            tags.append(tag)

    return tags, pr_links


def correlate_claude_sessions(conn: sqlite3.Connection | None = None) -> int:
    """Derive auto_tags + pr_links for every Claude session. Returns count updated."""
    close = False
    if conn is None:
        conn = get_db()
        close = True

    pr_rows_by_branch: dict[str, list[sqlite3.Row]] = {}
    pr_rows_by_session: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute(
        "SELECT repo, pr_number, branch, chat_session_id FROM pr_subscriptions"
    ).fetchall():
        if row["branch"]:
            pr_rows_by_branch.setdefault(row["branch"], []).append(row)
        if row["chat_session_id"]:
            pr_rows_by_session.setdefault(row["chat_session_id"], []).append(row)

    events = conn.execute(
        """SELECT json_extract(metadata,'$.session_id') AS session_id,
                  json_extract(metadata,'$.branch') AS branch,
                  json_extract(metadata,'$.cwd') AS cwd,
                  project
           FROM events WHERE source='claude_sessions'"""
    ).fetchall()

    updated = 0
    for ev in events:
        sid = ev["session_id"]
        if not sid:
            continue
        tags, pr_links = _derive_auto_tags(
            sid, ev["project"], ev["cwd"], ev["branch"], pr_rows_by_branch, pr_rows_by_session
        )
        existing = _load_row(conn, sid) or {}
        if (
            _parse_list(existing.get("auto_tags")) == tags
            and _parse_list(existing.get("pr_links")) == pr_links
        ):
            continue
        set_auto(conn, sid, tags, pr_links)
        updated += 1

    if close:
        conn.close()
    return updated
