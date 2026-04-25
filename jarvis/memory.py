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


def _group_sprint_tickets(conn) -> list[dict]:
    """Return active-sprint tickets grouped by board and bucket.

    Returns a list — one entry per subscribed board that has tickets. Each
    entry has {board_id, host, project_key, nickname, sprint_name,
    mine, unassigned, others}. The three bucket lists contain ticket dicts
    with fields key, status, summary, assignee, issue_type, priority, url.
    Done/closed/won't do tickets are filtered out.

    This is the single source of truth for sprint data — the CLI briefing
    (`_active_sprint_section`) renders it as markdown, the web dashboard
    (`api_upcoming`) ships it as JSON.
    """
    subs = list_jira_board_subs(conn)
    if not subs:
        return []

    rows = conn.execute(
        "SELECT name, metadata FROM entities WHERE kind='jira_issue' AND metadata IS NOT NULL"
    ).fetchall()

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

    _DONE = {"done", "closed", "won't do"}
    out: list[dict] = []
    for sub in subs:
        tickets = by_board.get(sub["board_id"], [])
        if not tickets:
            continue
        mine, unassigned, others = [], [], []
        for t in tickets:
            status = (t.get("status") or "").strip()
            if status.lower() in _DONE:
                continue
            row = {
                "key": t["key"],
                "status": status,
                "summary": (t.get("summary") or "").strip(),
                "assignee": (t.get("assignee") or "").strip(),
                "issue_type": (t.get("issue_type") or "").strip(),
                "priority": (t.get("priority") or "").strip(),
                "url": t.get("url") or "",
            }
            bucket = t.get("bucket")
            if bucket == "mine":
                mine.append(row)
            elif bucket == "unassigned":
                unassigned.append(row)
            elif bucket == "others":
                others.append(row)

        if not (mine or unassigned or others):
            continue
        sprint_name = tickets[0].get("sprint_name") or ""
        out.append(
            {
                "board_id": sub["board_id"],
                "host": sub["host"],
                "project_key": sub["project_key"],
                "nickname": sub["nickname"],
                "sprint_name": sprint_name,
                "mine": mine,
                "unassigned": unassigned,
                "others": others,
            }
        )
    return out


def _recent_nonsprint_jira(conn) -> list[dict]:
    """Tickets tagged 'recent' that are NOT on any currently-watched sprint.

    Surfaced separately from the sprint section so the user sees tickets
    they've touched outside (or cross-team) without drowning in sprint lists.
    """
    rows = conn.execute(
        "SELECT name, metadata FROM entities WHERE kind='jira_issue' AND metadata IS NOT NULL"
    ).fetchall()

    _DONE = {"done", "closed", "won't do"}
    out: list[dict] = []
    for r in rows:
        meta = json.loads(r["metadata"])
        tags = meta.get("source_tags") or []
        if "recent" not in tags:
            continue
        if any(t.startswith("board:") for t in tags):
            continue
        status = (meta.get("status") or "").strip()
        if status.lower() in _DONE:
            continue
        out.append(
            {
                "key": r["name"],
                "status": status,
                "summary": (meta.get("summary") or "").strip(),
                "assignee": (meta.get("assignee") or "").strip(),
                "issue_type": (meta.get("issue_type") or "").strip(),
                "priority": (meta.get("priority") or "").strip(),
                "url": meta.get("url") or "",
            }
        )
    # Stable-ish order: by key descending so the most-recent PROJ-NNNN sit on top.
    out.sort(key=lambda t: t["key"], reverse=True)
    return out


def _active_sprint_section(conn) -> str:
    """Markdown "Jira" block for the CLI briefing — sprints + recent tickets."""
    groups = _group_sprint_tickets(conn)
    recent_only = _recent_nonsprint_jira(conn)
    if not groups and not recent_only:
        return ""

    out: list[str] = ["## Jira"]
    if groups:
        out.append("### Active Sprints")
    for g in groups:
        header = f"### {g['nickname']}"
        if g["sprint_name"]:
            header += f" — {g['sprint_name']}"
        out.append(header)

        if g["mine"]:
            out.append("**Mine:**")
            for t in g["mine"]:
                out.append(f"- **{t['key']}** ({t['status']}) {t['summary']}".rstrip())
        if g["unassigned"]:
            n = len(g["unassigned"])
            out.append(f"**Unassigned (up for grabs, {n} tickets):**")
            for t in g["unassigned"][:10]:
                out.append(f"- **{t['key']}** ({t['status']}) {t['summary']}".rstrip())
            if n > 10:
                out.append(f"- _…and {n - 10} more_")
        if g["others"]:
            n = len(g["others"])
            out.append(f"**In flight (others, {n} tickets):**")
            for t in g["others"][:5]:
                out.append(f"- {t['key']} ({t['status']}) — {t['assignee']}")
            if n > 5:
                out.append(f"- _…and {n - 5} more_")

    if recent_only:
        out.append("")
        out.append(f"### Recent tickets (not on any watched sprint, {len(recent_only)})")
        for t in recent_only[:10]:
            out.append(f"- **{t['key']}** ({t['status']}) {t['summary']}".rstrip())
        if len(recent_only) > 10:
            out.append(f"- _…and {len(recent_only) - 10} more_")
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
