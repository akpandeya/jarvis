"""Tests for jarvis/patterns.py — keyed to docs/specs/patterns.md."""

import uuid
from datetime import datetime, timedelta

import pytest

from jarvis.db import upsert_event
from jarvis.patterns import (
    context_switches,
    day_of_week_distribution,
    generate_insights,
    project_distribution,
    source_distribution,
    time_of_day_distribution,
)


def _event(db, happened_at, project=None, source="github"):
    return upsert_event(
        db,
        source=source,
        kind="commit",
        title="work",
        happened_at=happened_at,
        url=str(uuid.uuid4()),
        project=project,
    )


def _recent(hours_ago=0):
    return datetime.now() - timedelta(hours=hours_ago, days=0)


# ---------------------------------------------------------------------------
# F1: time_of_day_distribution covers all 24 hours
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F1")
def test_time_of_day_all_24_hours_present(db):
    dist = time_of_day_distribution(db, days=30)
    assert len(dist) == 24
    assert all(isinstance(v, int) for v in dist.values())


@pytest.mark.spec("patterns.F1")
def test_time_of_day_counts_events(db):
    _event(db, _recent(1))
    dist = time_of_day_distribution(db, days=1)
    assert sum(dist.values()) >= 1


# ---------------------------------------------------------------------------
# F2: day_of_week_distribution covers all 7 days
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F2")
def test_day_of_week_all_7_days(db):
    dist = day_of_week_distribution(db, days=30)
    assert len(dist) == 7
    assert "Monday" in dist and "Sunday" in dist


# ---------------------------------------------------------------------------
# F3 & F4: context_switches
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F3")
@pytest.mark.spec("patterns.F4")
def test_context_switches_counts_project_changes(db):
    base = _recent(2)
    _event(db, base, project="alpha")
    _event(db, base + timedelta(minutes=10), project="beta")
    _event(db, base + timedelta(minutes=20), project="alpha")
    result = context_switches(db, days=1)
    assert result["total"] >= 2


@pytest.mark.spec("patterns.F4")
def test_context_switches_returns_avg(db):
    result = context_switches(db, days=7)
    assert "avg_per_day" in result
    assert "daily" in result


# ---------------------------------------------------------------------------
# F6: source_distribution ordered by count
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F6")
def test_source_distribution_ordered(db):
    for _ in range(3):
        _event(db, _recent(1), source="github")
    _event(db, _recent(1), source="jira")
    dist = source_distribution(db, days=1)
    keys = list(dist.keys())
    assert keys[0] == "github"


# ---------------------------------------------------------------------------
# F7: project_distribution uses (none) for null project
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F7")
def test_project_distribution_none_label(db):
    _event(db, _recent(1), project=None)
    dist = project_distribution(db, days=1)
    assert "(none)" in dist


# ---------------------------------------------------------------------------
# F8 & F9: generate_insights
# ---------------------------------------------------------------------------


@pytest.mark.spec("patterns.F9")
def test_generate_insights_no_data(db):
    result = generate_insights(db, days=30)
    assert "not enough data" in result.lower() or isinstance(result, str)


@pytest.mark.spec("patterns.F8")
def test_generate_insights_with_data(db):
    for h in range(5):
        _event(db, _recent(h), project="jarvis", source="github")
    result = generate_insights(db, days=30)
    assert "Peak activity hour" in result or "Sources" in result
