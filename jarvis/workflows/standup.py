from __future__ import annotations

from jarvis.brain import summarize_events
from jarvis.db import get_db, query_events


def generate_standup(
    days: int = 1,
    project: str | None = None,
    source: str | None = None,
) -> str:
    """Generate standup notes from recent activity."""
    conn = get_db()
    events = query_events(conn, source=source, project=project, days=days, limit=100)
    conn.close()

    if not events:
        return "No activity found for the standup period."

    return summarize_events(events, prompt_type="standup", days=days)
