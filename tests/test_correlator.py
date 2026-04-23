"""Tests for jarvis/correlator.py — keyed to docs/specs/correlator.md."""

from datetime import UTC, datetime

import pytest

from jarvis.correlator import correlate_events, extract_ticket_ids, find_related_events
from jarvis.db import upsert_event


def _now():
    return datetime.now(UTC)


def _event(db, title, url, source="github", kind="commit"):
    return upsert_event(db, source=source, kind=kind, title=title, happened_at=_now(), url=url)


# --- F1: extract ticket IDs and link to events ---


@pytest.mark.spec("correlator.F1")
def test_correlate_links_ticket_in_title(db):
    _event(db, "Fix PROJ-42 crash", "u1", kind="pr_opened")
    links = correlate_events(db)
    assert links >= 1
    entity = db.execute("SELECT * FROM entities WHERE kind='ticket' AND name='PROJ-42'").fetchone()
    assert entity is not None


@pytest.mark.spec("correlator.F1")
def test_extract_ticket_ids_finds_pattern(db):
    ids = extract_ticket_ids("Fixes TGH-123 and also ABC-9")
    assert "TGH-123" in ids
    assert "ABC-9" in ids


# --- F2: multiple events linked to same ticket entity ---


@pytest.mark.spec("correlator.F2")
def test_multiple_events_share_ticket_entity(db):
    _event(db, "PROJ-10 wip", "u1")
    _event(db, "PROJ-10 story", "u2", source="jira", kind="ticket")
    correlate_events(db)
    entity = db.execute("SELECT id FROM entities WHERE name='PROJ-10'").fetchone()
    count = db.execute(
        "SELECT COUNT(*) FROM event_entities WHERE entity_id=?", (entity["id"],)
    ).fetchone()[0]
    assert count == 2


# --- F3: no ticket IDs → no entity link ---


@pytest.mark.spec("correlator.F3")
def test_no_ticket_ids_no_link(db):
    _event(db, "Bump version", "u1", source="git")
    correlate_events(db)
    count = db.execute("SELECT COUNT(*) FROM entities WHERE kind='ticket'").fetchone()[0]
    assert count == 0


# --- F4 & F5: find_related_events ---


@pytest.mark.spec("correlator.F4")
@pytest.mark.spec("correlator.F5")
def test_find_related_events_excludes_self(db):
    id1 = _event(db, "PROJ-7 fix", "u1")
    _event(db, "PROJ-7 task", "u2", source="jira", kind="ticket")
    correlate_events(db)
    related = find_related_events(db, id1)
    related_ids = [r["id"] for r in related]
    assert id1 not in related_ids
    assert len(related) >= 1


# --- F6: returns count of links ---


@pytest.mark.spec("correlator.F6")
def test_correlate_returns_link_count(db):
    _event(db, "PROJ-1 and PROJ-2", "u1")
    count = correlate_events(db)
    assert count == 2
