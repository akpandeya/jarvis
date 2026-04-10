"""Claude integration via the `claude` CLI.

Uses `claude -p --bare` (print mode) — no API keys needed,
piggybacks on your existing Claude Code authentication.
"""

from __future__ import annotations

import shutil
import subprocess

from jarvis.models import Event


def _standup_prompt(days: int = 1) -> str:
    if days <= 1:
        period = "Yesterday"
    else:
        period = f"Last {days} days"
    return (
        "You are a personal engineering assistant generating standup notes. "
        f"The user was away for {days} day(s) and needs a catchup summary.\n\n"
        f"Given a list of work events, produce concise standup notes in this format:\n\n"
        f"**{period}:**\n- bullet points of what was done (group by day if multi-day)\n\n"
        "**Today:**\n- inferred next steps based on open items\n\n"
        "**Blockers:**\n- any blockers or items needing attention (or 'None')\n\n"
        "Keep it concise. Group related items. "
        "Use project names and ticket/PR numbers when available. No fluff."
    )


SYSTEM_PROMPTS = {
    "weekly": (
        "You are a personal engineering assistant generating a weekly summary. "
        "Given a list of work events from the past week, produce a summary with:\n\n"
        "**Key accomplishments:**\n- major items shipped, merged, or completed\n\n"
        "**In progress:**\n- items still being worked on\n\n"
        "**Themes:**\n- 1-2 sentence observation about where time was spent\n\n"
        "Be concise. Group by project when it helps clarity."
    ),
    "context": (
        "You are a personal engineering assistant providing session context. "
        "Given recent work events, produce a brief context briefing that helps the user "
        "quickly recall what they've been working on. Include:\n"
        "- Recent sessions and what was accomplished\n"
        "- Open items (PRs awaiting review, in-progress tickets)\n"
        "- Upcoming meetings if any\n"
        "Keep it under 200 words."
    ),
    "query": (
        "You are a personal engineering assistant answering questions about the user's work history. "
        "You are given a set of work events as context. Answer the user's question based on these events. "
        "Be specific — reference project names, PR numbers, ticket IDs, and dates. "
        "If the events don't contain enough information to answer, say so."
    ),
}


def _call_claude(system_prompt: str, user_message: str) -> str:
    """Call claude CLI in print mode with a system prompt and user message."""
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI not found. Install Claude Code first.")

    result = subprocess.run(
        [
            "claude", "-p",
            "--bare",
            "--append-system-prompt", system_prompt,
        ],
        input=user_message,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")

    return result.stdout.strip()


def _format_events(events: list[Event]) -> str:
    if not events:
        return "No events found for this period."

    lines: list[str] = []
    for e in events:
        ts = e.happened_at.strftime("%Y-%m-%d %H:%M")
        project = f"[{e.project}]" if e.project else ""
        url_part = f" ({e.url})" if e.url else ""
        meta = ""
        if e.metadata:
            if "sha" in e.metadata:
                meta = f" sha:{e.metadata['sha'][:8]}"
            if "number" in e.metadata:
                meta = f" #{e.metadata['number']}"
            if "state" in e.metadata:
                meta += f" state:{e.metadata['state']}"

        lines.append(f"- {ts} {e.source}/{e.kind} {project} {e.title}{meta}{url_part}")

        if e.body and len(e.body) < 500:
            lines.append(f"  {e.body[:300]}")

    return "\n".join(lines)


def summarize_events(
    events: list[Event],
    prompt_type: str,
    days: int = 1,
) -> str:
    """Generate a summary from a list of events using Claude."""
    if prompt_type == "standup":
        system = _standup_prompt(days)
    else:
        system = SYSTEM_PROMPTS[prompt_type]
    events_text = _format_events(events)
    return _call_claude(system, events_text)


def answer_query(query: str, events: list[Event]) -> str:
    """Answer a natural language question using event context."""
    system = SYSTEM_PROMPTS["query"]
    events_text = _format_events(events)
    return _call_claude(system, f"Context events:\n{events_text}\n\nQuestion: {query}")
