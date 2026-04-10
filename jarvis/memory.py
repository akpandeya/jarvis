"""Session memory — capture and replay context across Claude sessions."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.brain import _call_claude, _format_events
from jarvis.db import get_db, list_sessions, query_events, save_session


def capture_session(project: str | None = None, days: int = 1) -> str:
    """Capture current work as a session snapshot.

    Summarizes recent events and stores them as a session record.
    Returns the generated summary.
    """
    conn = get_db()
    events = query_events(conn, project=project, days=days, limit=100)

    if not events:
        summary = "No recent activity to capture."
    else:
        events_text = _format_events(events)
        summary = _call_claude(
            "Summarize what was accomplished in this work session in 3-5 concise bullet points. "
            "Include project names, ticket IDs, and key decisions. No preamble.",
            events_text,
        )

    save_session(conn, context=summary, project=project)
    conn.close()
    return summary


def generate_context(project: str | None = None, days: int = 2) -> str:
    """Generate a context briefing from recent sessions and events.

    This is what gets injected at the start of a new Claude session
    to give continuity.
    """
    conn = get_db()

    # Gather recent sessions
    sessions = list_sessions(conn, project=project, limit=5)

    # Gather recent events
    events = query_events(conn, project=project, days=days, limit=100)
    conn.close()

    # Build the context prompt
    parts: list[str] = []

    if sessions:
        parts.append("## Recent Sessions")
        for s in sessions:
            proj = f"[{s['project']}] " if s.get("project") else ""
            ts = s["started_at"][:16]
            parts.append(f"- {ts} {proj}{s['context']}")

    if events:
        parts.append("\n## Recent Events")
        parts.append(_format_events(events))

    if not parts:
        return "No recent activity or sessions found."

    context_input = "\n".join(parts)

    return _call_claude(
        "You are a personal engineering assistant providing session context. "
        "Given recent sessions and work events, produce a brief context briefing that helps "
        "the user quickly recall what they've been working on. Format:\n\n"
        "**Recent Work:**\n- what was done across projects\n\n"
        "**Open Items:**\n- in-progress tickets, PRs awaiting review\n\n"
        "**Next Steps:**\n- what to pick up\n\n"
        "Keep it under 200 words. Be specific with ticket/PR numbers.",
        context_input,
    )


def remember_note(note: str, project: str | None = None) -> str:
    """Store a manual note as a session record."""
    conn = get_db()
    session_id = save_session(conn, context=note, project=project)
    conn.close()
    return session_id
