"""Tests for jarvis/db.py — keyed to docs/specs/db.md."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.db import (
    Suggestion,
    _connect,
    dismiss_suggestion,
    get_pending_suggestions,
    init_db,
    insert_activity,
    query_events,
    search_events,
    snooze_suggestion,
    upsert_entity,
    upsert_event,
    upsert_suggestion,
)


def _now():
    return datetime.now(UTC)


# --- F1: migrations run in order ---


@pytest.mark.spec("db.F1")
def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = _connect(db_path)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "events" in tables
    assert "activity_log" in tables
    assert "suggestions" in tables
    conn.close()


# --- F2: get_db initialises if missing ---


@pytest.mark.spec("db.F2")
def test_get_db_initialises_missing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "new.db"
    monkeypatch.setattr("jarvis.db.DB_PATH", db_path)
    from jarvis.db import get_db

    conn = get_db(db_path)
    assert db_path.exists()
    conn.close()


# --- F3: upsert_event ignores duplicates ---


@pytest.mark.spec("db.F3")
def test_upsert_event_ignores_duplicate(db):
    kwargs = dict(
        source="github",
        kind="pr_opened",
        title="Fix bug",
        happened_at=_now(),
        url="https://example.com/pr/1",
    )
    id1 = upsert_event(db, **kwargs)
    id2 = upsert_event(db, **kwargs)
    count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 1
    assert id1 == id2  # same row returned on duplicate


# --- F4: insert_activity returns True on new row, False on duplicate ---


@pytest.mark.spec("db.F4")
def test_insert_activity_returns_true_on_new(db):
    result = insert_activity(
        db, source="shell", kind="shell_cmd", happened_at=_now(), title="git status"
    )
    assert result is True


@pytest.mark.spec("db.F4")
def test_insert_activity_returns_false_on_duplicate(db):
    kwargs = dict(source="shell", kind="shell_cmd", happened_at=_now(), title="git status")
    insert_activity(db, **kwargs)
    result = insert_activity(db, **kwargs)
    assert result is False


# --- F5: query_events respects days filter ---


@pytest.mark.spec("db.F5")
def test_query_events_respects_days_filter(db):
    old = _now() - timedelta(days=10)
    recent = _now() - timedelta(hours=1)
    upsert_event(db, source="git", kind="commit", title="old commit", happened_at=old)
    upsert_event(
        db, source="git", kind="commit", title="recent commit", happened_at=recent, url="u1"
    )
    events = query_events(db, days=7)
    titles = [e.title for e in events]
    assert "recent commit" in titles
    assert "old commit" not in titles


# --- F6: search_events uses FTS ---


@pytest.mark.spec("db.F6")
def test_search_events_returns_fts_matches(db):
    upsert_event(
        db,
        source="jira",
        kind="ticket",
        title="Deploy the payment service",
        happened_at=_now(),
        url="u1",
    )
    upsert_event(
        db, source="jira", kind="ticket", title="Fix login bug", happened_at=_now(), url="u2"
    )
    results = search_events(db, "payment")
    assert len(results) == 1
    assert results[0].title == "Deploy the payment service"


# --- F7: upsert_entity deduplicates ---


@pytest.mark.spec("db.F7")
def test_upsert_entity_returns_existing_id(db):
    id1 = upsert_entity(db, kind="person", name="Alice")
    id2 = upsert_entity(db, kind="person", name="Alice")
    assert id1 == id2
    count = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert count == 1


# --- F8: upsert_suggestion updates in place ---


@pytest.mark.spec("db.F8")
def test_upsert_suggestion_updates_existing(db):
    s = Suggestion(rule_id="test_rule", message="Do something", action="jarvis foo", priority=50)
    upsert_suggestion(db, s)
    s2 = Suggestion(
        rule_id="test_rule", message="Updated message", action="jarvis bar", priority=80
    )  # noqa: E501
    upsert_suggestion(db, s2)
    count = db.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
    assert count == 1
    row = db.execute(
        "SELECT message, priority FROM suggestions WHERE rule_id='test_rule'"
    ).fetchone()
    assert row["message"] == "Updated message"
    assert row["priority"] == 80


# --- F9: get_pending excludes dismissed and snoozed ---


@pytest.mark.spec("db.F9")
def test_get_pending_excludes_dismissed(db):
    upsert_suggestion(db, Suggestion(rule_id="r1", message="A", action="x", priority=50))
    dismiss_suggestion(db, "r1")
    assert get_pending_suggestions(db) == []


@pytest.mark.spec("db.F9")
def test_get_pending_excludes_active_snooze(db):
    upsert_suggestion(db, Suggestion(rule_id="r2", message="B", action="y", priority=50))
    snooze_suggestion(db, "r2", _now() + timedelta(hours=1))
    assert get_pending_suggestions(db) == []


@pytest.mark.spec("db.F9")
def test_get_pending_includes_expired_snooze(db):
    upsert_suggestion(db, Suggestion(rule_id="r3", message="C", action="z", priority=50))
    snooze_suggestion(db, "r3", _now() - timedelta(seconds=1))
    assert len(get_pending_suggestions(db)) == 1


# --- F11: WAL mode enabled ---


@pytest.mark.spec("db.F11")
def test_wal_mode_enabled(db):
    row = db.execute("PRAGMA journal_mode").fetchone()
    assert row[0] == "wal"
