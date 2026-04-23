"""Tests for jarvis/workflows/ — keyed to docs/specs/workflows.md."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from jarvis.db import upsert_event
from jarvis.workflows.standup import generate_standup
from jarvis.workflows.weekly_summary import generate_weekly


def _event(db, title="work", days_ago=0, project=None, source="github"):
    return upsert_event(
        db,
        source=source,
        kind="commit",
        title=title,
        happened_at=datetime.now(UTC) - timedelta(days=days_ago),
        url=str(uuid.uuid4()),
        project=project,
    )


# ---------------------------------------------------------------------------
# Standup
# ---------------------------------------------------------------------------


@pytest.mark.spec("workflows.F1")
def test_generate_standup_no_events_skips_claude(db, monkeypatch):
    monkeypatch.setattr("jarvis.workflows.standup.get_db", lambda: db)
    monkeypatch.setattr("jarvis.workflows.standup.query_events", lambda *a, **kw: [])
    with patch("jarvis.brain._call_claude") as mock_claude:
        result = generate_standup()
        mock_claude.assert_not_called()
    assert "No activity" in result


@pytest.mark.spec("workflows.F2")
def test_generate_standup_single_day_prompt(db, monkeypatch):
    _event(db)
    monkeypatch.setattr("jarvis.workflows.standup.get_db", lambda: db)
    with patch("jarvis.brain._call_claude") as mock_claude:
        mock_claude.return_value = "standup"
        generate_standup()
        system_prompt = mock_claude.call_args[0][0]
    assert "Yesterday" in system_prompt


@pytest.mark.spec("workflows.F3")
def test_generate_standup_multi_day_prompt(db, monkeypatch):
    _event(db, days_ago=2)
    monkeypatch.setattr("jarvis.workflows.standup.get_db", lambda: db)
    with patch("jarvis.brain._call_claude") as mock_claude:
        mock_claude.return_value = "standup"
        generate_standup(days=3)
        system_prompt = mock_claude.call_args[0][0]
    assert "Last 3 days" in system_prompt


@pytest.mark.spec("workflows.F4")
def test_generate_standup_project_filter(db, monkeypatch):
    _event(db, project="alpha")
    _event(db, project="beta")
    monkeypatch.setattr("jarvis.workflows.standup.get_db", lambda: db)
    with patch("jarvis.brain._call_claude") as mock_claude:
        mock_claude.return_value = "standup"
        generate_standup(project="alpha")
        events_text = mock_claude.call_args[0][1]
    assert "alpha" in events_text
    assert "beta" not in events_text


# ---------------------------------------------------------------------------
# Weekly summary
# ---------------------------------------------------------------------------


@pytest.mark.spec("workflows.F6")
def test_generate_weekly_no_events_skips_claude(db, monkeypatch):
    monkeypatch.setattr("jarvis.workflows.weekly_summary.get_db", lambda: db)
    monkeypatch.setattr("jarvis.workflows.weekly_summary.query_events", lambda *a, **kw: [])
    with patch("jarvis.brain._call_claude") as mock_claude:
        result = generate_weekly()
        mock_claude.assert_not_called()
    assert "No activity" in result


@pytest.mark.spec("workflows.F7")
def test_generate_weekly_queries_7_days(db, monkeypatch):
    captured = {}
    original_query = __import__("jarvis.db", fromlist=["query_events"]).query_events

    def capture_query(conn, **kwargs):
        captured.update(kwargs)
        return original_query(conn, **kwargs)

    monkeypatch.setattr("jarvis.workflows.weekly_summary.get_db", lambda: db)
    monkeypatch.setattr("jarvis.workflows.weekly_summary.query_events", capture_query)
    with patch("jarvis.brain._call_claude", return_value="summary"):
        _event(db)
        generate_weekly()
    assert captured.get("days") == 7


@pytest.mark.spec("workflows.F9")
def test_generate_weekly_project_filter(db, monkeypatch):
    _event(db, project="jarvis")
    _event(db, project="other")
    monkeypatch.setattr("jarvis.workflows.weekly_summary.get_db", lambda: db)
    with patch("jarvis.brain._call_claude") as mock_claude:
        mock_claude.return_value = "summary"
        generate_weekly(project="jarvis")
        events_text = mock_claude.call_args[0][1]
    assert "jarvis" in events_text
    assert "other" not in events_text
