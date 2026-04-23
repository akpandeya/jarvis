"""Deterministic suggestion rule engine.

Each rule inspects the local DB and returns a Suggestion or None.
No LLM calls — all logic is pure SQL + datetime arithmetic.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jarvis.db import (
    Suggestion,
    dismiss_suggestion,
    get_pending_suggestions,
    snooze_suggestion,
    upsert_suggestion,
)

__all__ = [
    "evaluate_all",
    "get_pending",
    "dismiss",
    "snooze",
    "Suggestion",
]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _no_standup(conn: sqlite3.Connection) -> Suggestion | None:
    now = datetime.now()
    if now.weekday() >= 5:  # weekend
        return None
    if not (9 <= now.hour < 11):
        return None
    today = now.date().isoformat()
    row = conn.execute(
        "SELECT id FROM summaries WHERE kind = 'standup' AND created_at >= ? LIMIT 1",
        (today,),
    ).fetchone()
    if row:
        return None
    return Suggestion(
        rule_id="no_standup",
        message="No standup generated yet today",
        action="jarvis standup",
        priority=80,
    )


def _stale_ingest(conn: sqlite3.Connection) -> Suggestion | None:
    row = conn.execute("SELECT MAX(happened_at) as latest FROM events").fetchone()
    if not row or not row["latest"]:
        return Suggestion(
            rule_id="stale_ingest",
            message="No events ingested yet",
            action="jarvis ingest",
            priority=70,
        )
    latest = datetime.fromisoformat(row["latest"])
    if datetime.now() - latest > timedelta(hours=2):
        return Suggestion(
            rule_id="stale_ingest",
            message="Activity not ingested in the last 2 hours",
            action="jarvis ingest",
            priority=70,
        )
    return None


def _meeting_soon(conn: sqlite3.Connection) -> Suggestion | None:
    now = datetime.now()
    window_end = (now + timedelta(minutes=30)).isoformat()
    now_iso = now.isoformat()
    rows = conn.execute(
        "SELECT title, metadata FROM events WHERE source = 'gcal' "
        "AND happened_at BETWEEN ? AND ? ORDER BY happened_at LIMIT 1",
        (now_iso, window_end),
    ).fetchall()
    for row in rows:
        import json

        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        attendees = meta.get("attendees", [])
        if len(attendees) > 1:
            title = row["title"]
            return Suggestion(
                rule_id="meeting_soon",
                message=f"Meeting starting soon: {title}",
                action=f'jarvis prep "{title}"',
                priority=90,
            )
    return None


def _unsaved_session(conn: sqlite3.Connection) -> Suggestion | None:
    row = conn.execute(
        "SELECT started_at FROM sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    last_save = datetime.fromisoformat(row["started_at"])
    if datetime.now() - last_save <= timedelta(hours=4):
        return None
    since_iso = last_save.isoformat()
    count_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM events WHERE happened_at > ?", (since_iso,)
    ).fetchone()
    if count_row and count_row["cnt"] > 10:
        return Suggestion(
            rule_id="unsaved_session",
            message="Session not saved in 4+ hours with new activity",
            action="jarvis session save",
            priority=60,
        )
    return None


def _context_drift(conn: sqlite3.Connection) -> Suggestion | None:
    since = (datetime.now() - timedelta(hours=2)).isoformat()
    row = conn.execute(
        "SELECT COUNT(DISTINCT project) as cnt FROM events "
        "WHERE happened_at >= ? AND project IS NOT NULL",
        (since,),
    ).fetchone()
    if row and row["cnt"] >= 3:
        return Suggestion(
            rule_id="context_drift",
            message=f"{row['cnt']} projects active in the last 2 hours",
            action="jarvis context",
            priority=50,
        )
    return None


def _update_available(conn: sqlite3.Connection) -> Suggestion | None:
    now = datetime.now()
    if not (8 <= now.hour < 9):
        return None
    today = now.date().isoformat()
    # Fire at most once per day
    row = conn.execute(
        "SELECT id FROM suggestions WHERE rule_id='update_available' "
        "AND created_at >= ? AND dismissed=0",
        (today,),
    ).fetchone()
    if row:
        return None
    try:
        from jarvis import __version__
        from jarvis.updater import get_latest_version, update_available

        if not update_available():
            return None
        latest = get_latest_version()
        return Suggestion(
            rule_id="update_available",
            message=f"Jarvis {latest} is available (installed: {__version__})",
            action=(
                "curl -sSf https://raw.githubusercontent.com/akpandeya/jarvis/main"
                "/scripts/bootstrap.sh | bash"
            ),
            priority=70,
        )
    except Exception:
        return None


_RULES = [
    _no_standup,
    _stale_ingest,
    _meeting_soon,
    _unsaved_session,
    _context_drift,
    _update_available,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_all(conn: sqlite3.Connection) -> int:
    """Run all rules, upsert results. Returns count of suggestions fired."""
    fired = 0
    for rule in _RULES:
        try:
            suggestion = rule(conn)
        except Exception:
            continue
        if suggestion is not None:
            upsert_suggestion(conn, suggestion)
            fired += 1
    return fired


def get_pending(conn: sqlite3.Connection) -> list[Suggestion]:
    return get_pending_suggestions(conn)


def dismiss(conn: sqlite3.Connection, rule_id: str) -> None:
    dismiss_suggestion(conn, rule_id)


def snooze(conn: sqlite3.Connection, rule_id: str, minutes: int = 60) -> None:
    until = datetime.now() + timedelta(minutes=minutes)
    snooze_suggestion(conn, rule_id, until)
