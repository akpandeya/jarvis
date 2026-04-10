"""Cross-source correlation engine.

Links events from different sources that are related — e.g., a GitHub PR
to a Jira ticket based on branch names, PR titles, or commit messages
containing ticket IDs.
"""

from __future__ import annotations

import re
import sqlite3

from jarvis.db import get_db, link_event_entity, upsert_entity

# Matches patterns like JIRA-123, PROJ-456, ABC-1
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_ticket_ids(text: str) -> list[str]:
    """Extract Jira-style ticket IDs from text."""
    return TICKET_RE.findall(text)


def correlate_events(conn: sqlite3.Connection | None = None) -> int:
    """Scan recent events and link those that reference the same tickets.

    Returns the number of new links created.
    """
    if conn is None:
        conn = get_db()

    links_created = 0

    # Find all events that contain ticket IDs in their title or body
    rows = conn.execute("SELECT id, source, kind, title, body, project FROM events").fetchall()

    # Build a map: ticket_id -> list of event_ids that reference it
    ticket_events: dict[str, list[str]] = {}

    for row in rows:
        event_id = row["id"]
        text = (row["title"] or "") + " " + (row["body"] or "")
        tickets = extract_ticket_ids(text)

        for ticket_id in tickets:
            # Create/find the ticket entity
            entity_id = upsert_entity(conn, kind="ticket", name=ticket_id)

            # Link this event to the ticket
            link_event_entity(conn, event_id, entity_id, "relates_to")
            links_created += 1

            ticket_events.setdefault(ticket_id, []).append(event_id)

    return links_created


def find_related_events(conn: sqlite3.Connection, event_id: str) -> list[dict]:
    """Find events related to a given event through shared entities."""
    rows = conn.execute(
        """SELECT DISTINCT e.id, e.source, e.kind, e.title, e.happened_at, e.project
           FROM events e
           JOIN event_entities ee1 ON e.id = ee1.event_id
           JOIN event_entities ee2 ON ee1.entity_id = ee2.entity_id
           WHERE ee2.event_id = ? AND e.id != ?
           ORDER BY e.happened_at DESC
           LIMIT 20""",
        (event_id, event_id),
    ).fetchall()
    return [dict(r) for r in rows]
