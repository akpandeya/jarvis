from __future__ import annotations

from jarvis.brain import summarize_events
from jarvis.db import get_db, query_events


def generate_weekly(
    project: str | None = None,
    source: str | None = None,
) -> str:
    """Generate a weekly summary from recent activity."""
    conn = get_db()
    events = query_events(conn, source=source, project=project, days=7, limit=200)
    conn.close()

    if not events:
        return "No activity found for the past week."

    return summarize_events(events, prompt_type="weekly")
