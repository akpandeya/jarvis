"""Tests for jarvis/resolver.py — keyed to docs/specs/resolver.md."""

import json
from datetime import UTC, datetime

import pytest

from jarvis.db import link_event_entity, upsert_entity, upsert_event
from jarvis.resolver import list_people, resolve_entities


def _now():
    return datetime.now(UTC)


def _add_person(db, name, email=None):
    meta = {"email": email} if email else None
    return upsert_entity(db, kind="person", name=name, metadata=meta)


# --- F1: merge by normalised name ---


@pytest.mark.spec("resolver.F1")
def test_merge_by_normalised_name(db):
    _add_person(db, "Alice Smith")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('id2', 'person', 'alice smith')")
    db.commit()
    merges = resolve_entities(db)
    assert merges == 1
    count = db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0]
    assert count == 1


# --- F2: merge by email prefix ---


@pytest.mark.spec("resolver.F2")
def test_merge_by_email_prefix(db):
    _add_person(db, "jsmith", email="jsmith@corp.com")
    _add_person(db, "John Smith", email="jsmith@personal.com")
    merges = resolve_entities(db)
    assert merges >= 1
    count = db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0]
    assert count == 1


# --- F3: event_entities repointed to canonical ---


@pytest.mark.spec("resolver.F3")
def test_event_entities_repointed(db):
    event_id = upsert_event(
        db, source="github", kind="commit", title="work", happened_at=_now(), url="u1"
    )
    dup_id = _add_person(db, "Bob")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('dup2', 'person', 'bob')")
    db.commit()
    link_event_entity(db, event_id, dup_id, "author")
    resolve_entities(db)
    remaining = db.execute(
        "SELECT entity_id FROM event_entities WHERE event_id=?", (event_id,)
    ).fetchone()
    assert remaining is not None
    # the linked entity should still exist
    entity = db.execute("SELECT id FROM entities WHERE id=?", (remaining["entity_id"],)).fetchone()
    assert entity is not None


# --- F5: duplicates deleted ---


@pytest.mark.spec("resolver.F5")
def test_duplicates_deleted(db):
    _add_person(db, "Carol")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('carol2', 'person', 'carol')")
    db.commit()
    resolve_entities(db)
    count = db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0]
    assert count == 1


# --- F6: canonical is longest name ---


@pytest.mark.spec("resolver.F6")
def test_canonical_is_longest_name(db):
    # "alice" and "Alice" normalise to the same key — longest name wins
    _add_person(db, "Alice")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('a2', 'person', 'Alice Johnson')")
    # make Alice Johnson appear as an alias of Alice so they merge
    db.execute("UPDATE entities SET aliases = '[\"alice\"]' WHERE id = 'a2'")
    db.commit()
    resolve_entities(db)
    canonical = db.execute("SELECT name FROM entities WHERE kind='person'").fetchone()["name"]
    assert canonical == "Alice Johnson"


# --- F7: all names collected as aliases ---


@pytest.mark.spec("resolver.F7")
def test_aliases_collected_canonical_not_aliased(db):
    # Two entities with same normalised name → merge; shorter becomes alias
    _add_person(db, "Bob")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('b2', 'person', 'BOB')")
    db.commit()
    resolve_entities(db)
    row = db.execute("SELECT name, aliases FROM entities WHERE kind='person'").fetchone()
    aliases = json.loads(row["aliases"]) if row["aliases"] else []
    assert row["name"] not in aliases
    # The non-canonical name should be an alias
    other = "BOB" if row["name"] == "Bob" else "Bob"
    assert other in aliases


# --- F8: returns merge count ---


@pytest.mark.spec("resolver.F8")
def test_returns_merge_count(db):
    _add_person(db, "Frank")
    db.execute("INSERT INTO entities (id, kind, name) VALUES ('f2', 'person', 'frank')")
    db.commit()
    assert resolve_entities(db) == 1


# --- F9: list_people includes event count ---


@pytest.mark.spec("resolver.F9")
def test_list_people_includes_event_count(db):
    eid = upsert_event(db, source="github", kind="commit", title="x", happened_at=_now(), url="u1")
    pid = _add_person(db, "Grace")
    link_event_entity(db, eid, pid, "author")
    people = list_people(db)
    assert len(people) == 1
    assert people[0]["name"] == "Grace"
    assert people[0]["event_count"] == 1
