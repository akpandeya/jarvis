"""Tests for jarvis/suggestions.py — keyed to docs/specs/suggestions_engine.md."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.db import Suggestion, save_session, upsert_event, upsert_suggestion
from jarvis.suggestions import dismiss, evaluate_all, get_pending, snooze


def _now():
    return datetime.now(UTC)


def _naive_now():
    return datetime.now()


def _insert_event(db, project=None, source="github", happened_at=None):
    import uuid

    return upsert_event(
        db,
        source=source,
        kind="commit",
        title="work",
        happened_at=happened_at or _now(),
        url=str(uuid.uuid4()),
        project=project,
    )


# ---------------------------------------------------------------------------
# evaluate_all
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F1")
def test_evaluate_all_returns_count(db):
    import uuid

    # Insert a stale event so stale_ingest fires
    upsert_event(
        db,
        source="github",
        kind="commit",
        title="old",
        happened_at=datetime.now(UTC) - timedelta(hours=3),
        url=str(uuid.uuid4()),
    )
    fired = evaluate_all(db)
    assert fired >= 1


@pytest.mark.spec("suggestions_engine.F1")
def test_evaluate_all_upserts_suggestions(db):
    import uuid

    upsert_event(
        db,
        source="github",
        kind="commit",
        title="old",
        happened_at=datetime.now(UTC) - timedelta(hours=3),
        url=str(uuid.uuid4()),
    )
    evaluate_all(db)
    rows = db.execute("SELECT * FROM suggestions").fetchall()
    assert len(rows) >= 1


@pytest.mark.spec("suggestions_engine.F2")
def test_evaluate_all_does_not_raise_on_rule_exception(db, monkeypatch):
    from jarvis import suggestions as sug_mod

    original_rules = sug_mod._RULES
    sug_mod._RULES = [lambda conn: 1 / 0]  # always raises
    try:
        fired = evaluate_all(db)
        assert fired == 0
    finally:
        sug_mod._RULES = original_rules


# ---------------------------------------------------------------------------
# stale_ingest rule
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F4")
def test_stale_ingest_silent_when_no_events(db):
    from jarvis.suggestions import _stale_ingest

    # No events on first install — should not nag
    suggestion = _stale_ingest(db)
    assert suggestion is None


@pytest.mark.spec("suggestions_engine.F4")
def test_stale_ingest_fires_when_last_event_old(db):
    from jarvis.suggestions import _stale_ingest

    old = _now() - timedelta(hours=3)
    _insert_event(db, happened_at=old)
    suggestion = _stale_ingest(db)
    assert suggestion is not None


@pytest.mark.spec("suggestions_engine.F4")
def test_stale_ingest_silent_when_recent(db):
    from jarvis.suggestions import _stale_ingest

    _insert_event(db, happened_at=_naive_now())
    suggestion = _stale_ingest(db)
    assert suggestion is None


# ---------------------------------------------------------------------------
# context_drift rule
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F5")
def test_context_drift_fires_with_3_projects(db):
    from jarvis.suggestions import _context_drift

    recent = _naive_now() - timedelta(minutes=30)
    for proj in ["alpha", "beta", "gamma"]:
        _insert_event(db, project=proj, happened_at=recent)
    suggestion = _context_drift(db)
    assert suggestion is not None
    assert suggestion.rule_id == "context_drift"


@pytest.mark.spec("suggestions_engine.F5")
def test_context_drift_silent_with_2_projects(db):
    from jarvis.suggestions import _context_drift

    recent = _naive_now() - timedelta(minutes=30)
    for proj in ["alpha", "beta"]:
        _insert_event(db, project=proj, happened_at=recent)
    suggestion = _context_drift(db)
    assert suggestion is None


# ---------------------------------------------------------------------------
# unsaved_session rule
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F6")
def test_unsaved_session_fires_when_stale(db):
    from jarvis.suggestions import _unsaved_session

    old_save = _naive_now() - timedelta(hours=5)
    save_session(db, context="old session", started_at=old_save)
    for _ in range(11):
        _insert_event(db, happened_at=_naive_now())
    suggestion = _unsaved_session(db)
    assert suggestion is not None
    assert suggestion.rule_id == "unsaved_session"


@pytest.mark.spec("suggestions_engine.F6")
def test_unsaved_session_silent_when_recent_save(db):
    from jarvis.suggestions import _unsaved_session

    save_session(db, context="fresh session")
    suggestion = _unsaved_session(db)
    assert suggestion is None


# ---------------------------------------------------------------------------
# meeting_soon rule
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F3")
def test_meeting_soon_fires_when_upcoming_with_attendees(db):
    from jarvis.suggestions import _meeting_soon

    soon = _naive_now() + timedelta(minutes=10)
    upsert_event(
        db,
        source="gcal",
        kind="meeting",
        title="Team sync",
        happened_at=soon,
        url="https://cal.google.com/e/1",
        metadata={"attendees": ["alice@corp.com", "bob@corp.com"]},
    )
    suggestion = _meeting_soon(db)
    assert suggestion is not None
    assert "Team sync" in suggestion.message


@pytest.mark.spec("suggestions_engine.F3")
def test_meeting_soon_silent_when_only_one_attendee(db):
    from jarvis.suggestions import _meeting_soon

    soon = _naive_now() + timedelta(minutes=10)
    upsert_event(
        db,
        source="gcal",
        kind="meeting",
        title="Solo block",
        happened_at=soon,
        url="https://cal.google.com/e/2",
        metadata={"attendees": ["me@corp.com"]},
    )
    suggestion = _meeting_soon(db)
    assert suggestion is None


# ---------------------------------------------------------------------------
# dismiss / snooze
# ---------------------------------------------------------------------------


@pytest.mark.spec("suggestions_engine.F8")
def test_dismiss_removes_from_pending(db):
    upsert_suggestion(db, Suggestion(rule_id="r1", message="x", action="y", priority=50))
    dismiss(db, "r1")
    assert get_pending(db) == []


@pytest.mark.spec("suggestions_engine.F9")
def test_snooze_removes_from_pending(db):
    upsert_suggestion(db, Suggestion(rule_id="r2", message="x", action="y", priority=50))
    snooze(db, "r2", minutes=60)
    assert get_pending(db) == []


@pytest.mark.spec("suggestions_engine.F7")
def test_get_pending_returns_by_priority(db):
    upsert_suggestion(db, Suggestion(rule_id="low", message="low", action="a", priority=10))
    upsert_suggestion(db, Suggestion(rule_id="high", message="high", action="b", priority=90))
    pending = get_pending(db)
    assert pending[0].rule_id == "high"
