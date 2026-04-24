"""Session memory — capture and replay context across Claude sessions."""

from __future__ import annotations

import json

from jarvis.brain import _call_claude, _format_events
from jarvis.db import get_db, list_jira_board_subs, list_sessions, query_events, save_session


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


def _active_sprint_section(conn) -> str:
    """Render a markdown "Active Sprint" block for each subscribed board.

    Returns the empty string when the user has no board subscriptions or the
    board has no active-sprint entities yet (e.g. before first ingest).
    Bucketing (mine / unassigned / others) is pre-computed by the
    JiraBoards integration via three disjoint JQL queries — we just render.
    """
    subs = list_jira_board_subs(conn)
    if not subs:
        return ""

    # Pull every jira_issue entity tagged for a subscribed board.
    rows = conn.execute(
        "SELECT name, metadata FROM entities WHERE kind='jira_issue' AND metadata IS NOT NULL"
    ).fetchall()

    # Group entities by board_id.
    by_board: dict[int, list[dict]] = {sub["board_id"]: [] for sub in subs}
    for r in rows:
        meta = json.loads(r["metadata"])
        tags = meta.get("source_tags") or []
        board_tag = next((t for t in tags if t.startswith("board:")), None)
        if not board_tag:
            continue
        try:
            bid = int(board_tag.split(":", 1)[1])
        except ValueError:
            continue
        if bid not in by_board:
            continue
        by_board[bid].append({"key": r["name"], **meta})

    if not any(by_board.values()):
        return ""

    out: list[str] = ["## Active Sprints"]
    for sub in subs:
        tickets = by_board.get(sub["board_id"], [])
        if not tickets:
            continue
        sprint_name = tickets[0].get("sprint_name") or ""
        header = f"### {sub['nickname']}"
        if sprint_name:
            header += f" — {sprint_name}"
        out.append(header)

        mine, unassigned, others = [], [], []
        for t in tickets:
            status = (t.get("status") or "").strip()
            if status.lower() in ("done", "closed", "won't do"):
                continue
            summary = (t.get("summary") or "").strip()
            bucket = t.get("bucket")
            if bucket == "mine":
                mine.append(f"- **{t['key']}** ({status}) {summary}".rstrip())
            elif bucket == "unassigned":
                unassigned.append(f"- **{t['key']}** ({status}) {summary}".rstrip())
            elif bucket == "others":
                assignee = (t.get("assignee") or "").strip()
                others.append(f"- {t['key']} ({status}) — {assignee}")

        if mine:
            out.append("**Mine:**")
            out.extend(mine)
        if unassigned:
            out.append(f"**Unassigned (up for grabs, {len(unassigned)} tickets):**")
            out.extend(unassigned[:10])
            if len(unassigned) > 10:
                out.append(f"- _…and {len(unassigned) - 10} more_")
        if others:
            out.append(f"**In flight (others, {len(others)} tickets):**")
            out.extend(others[:5])
            if len(others) > 5:
                out.append(f"- _…and {len(others) - 5} more_")
    return "\n".join(out) + "\n"


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

    # Gather active-sprint tickets (deterministic — rendered verbatim).
    sprint_section = _active_sprint_section(conn)
    conn.close()

    # Build the context prompt
    parts: list[str] = []

    if sprint_section:
        parts.append(sprint_section)

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

    llm_output = _call_claude(
        "You are a personal engineering assistant providing session context. "
        "Given recent sessions and work events, produce a brief context briefing that helps "
        "the user quickly recall what they've been working on. Format:\n\n"
        "**Recent Work:**\n- what was done across projects\n\n"
        "**Open Items:**\n- in-progress tickets, PRs awaiting review\n\n"
        "**Next Steps:**\n- what to pick up\n\n"
        "Keep it under 200 words. Be specific with ticket/PR numbers. "
        "If 'Active Sprints' data is included in the input, do NOT repeat "
        "those ticket lists verbatim — they are rendered separately for the "
        "user.",
        context_input,
    )

    # Prepend the deterministic sprint section so the user always sees it
    # even if the LLM trims it.
    if sprint_section:
        return sprint_section + "\n" + llm_output
    return llm_output


def remember_note(note: str, project: str | None = None) -> str:
    """Store a manual note as a session record."""
    conn = get_db()
    session_id = save_session(conn, context=note, project=project)
    conn.close()
    return session_id
