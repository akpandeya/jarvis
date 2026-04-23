"""Tests for jarvis/integrations/firefox.py — keyed to docs/specs/firefox.md."""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.integrations.firefox import Firefox, _profile_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USEC = 1_000_000


def _make_places_db(path: Path) -> None:
    """Create a minimal places.sqlite with the real Firefox schema."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE moz_places (
            id          INTEGER PRIMARY KEY,
            url         TEXT NOT NULL,
            title       TEXT,
            last_visit_date INTEGER
        );
        CREATE TABLE moz_historyvisits (
            id          INTEGER PRIMARY KEY,
            place_id    INTEGER NOT NULL,
            visit_date  INTEGER NOT NULL,
            visit_type  INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_visit(path: Path, url: str, title: str | None, visit_dt: datetime) -> None:
    visit_usec = int(visit_dt.timestamp() * _USEC)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO moz_places (url, title, last_visit_date) VALUES (?, ?, ?)",
        (url, title, visit_usec),
    )
    place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO moz_historyvisits (place_id, visit_date) VALUES (?, ?)",
        (place_id, visit_usec),
    )
    conn.commit()
    conn.close()


def _fake_profile(tmp_path: Path) -> Path:
    """Create a fake Firefox profile directory with a fresh places.sqlite."""
    profile_dir = tmp_path / "fake.default-release"
    profile_dir.mkdir()
    db = profile_dir / "places.sqlite"
    _make_places_db(db)
    return profile_dir


# ---------------------------------------------------------------------------
# F1 — finds default profile
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F1")
def test_profile_discovery_macos(tmp_path, monkeypatch):
    """On macOS, _profile_dir should return the .default-release directory."""
    monkeypatch.setattr(sys, "platform", "darwin")

    base = tmp_path / "Library" / "Application Support" / "Firefox" / "Profiles"
    base.mkdir(parents=True)
    profile = base / "abc123.default-release"
    profile.mkdir()
    (profile / "places.sqlite").touch()

    monkeypatch.setattr("jarvis.integrations.firefox.Path.home", lambda: tmp_path)

    result = _profile_dir()
    assert result == profile


@pytest.mark.spec("firefox.F1")
def test_profile_discovery_linux(tmp_path, monkeypatch):
    """On Linux, _profile_dir should return the .default-release directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    base = tmp_path / ".mozilla" / "firefox"
    base.mkdir(parents=True)
    profile = base / "xyz.default-release"
    profile.mkdir()
    (profile / "places.sqlite").touch()

    monkeypatch.setattr("jarvis.integrations.firefox.Path.home", lambda: tmp_path)

    result = _profile_dir()
    assert result == profile


# ---------------------------------------------------------------------------
# F2 — copies DB before reading
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F2")
def test_copies_db_before_reading(tmp_path, monkeypatch):
    """fetch_since should copy places.sqlite to a temp file."""
    profile = _fake_profile(tmp_path)
    now = datetime.now(UTC)
    _insert_visit(profile / "places.sqlite", "https://example.com", "Example", now)

    copied_paths: list[Path] = []
    real_copy2 = __import__("shutil").copy2

    def tracking_copy2(src, dst):
        copied_paths.append(Path(dst))
        real_copy2(src, dst)

    db_path = profile / "places.sqlite"
    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db_path)
    monkeypatch.setattr("jarvis.integrations.firefox.shutil.copy2", tracking_copy2)

    firefox = Firefox()
    since = now - timedelta(hours=1)
    firefox.fetch_since(since)

    assert len(copied_paths) == 1
    # The destination should have been a temp file (not the original)
    assert copied_paths[0] != profile / "places.sqlite"


# ---------------------------------------------------------------------------
# F3 — fetches only visits since cutoff
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F3")
def test_fetches_only_visits_after_cutoff(tmp_path, monkeypatch):
    """Only visits strictly after the `since` datetime should be returned."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"
    now = datetime.now(UTC)

    old_visit = now - timedelta(hours=3)
    recent_visit = now - timedelta(minutes=30)

    _insert_visit(db, "https://old.example.com", "Old", old_visit)
    _insert_visit(db, "https://recent.example.com", "Recent", recent_visit)

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    since = now - timedelta(hours=1)
    events = firefox.fetch_since(since)

    urls = [e.url for e in events]
    assert "https://recent.example.com" in urls
    assert "https://old.example.com" not in urls


# ---------------------------------------------------------------------------
# F4 — correct event fields
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F4")
def test_event_fields_are_correct(tmp_path, monkeypatch):
    """RawEvent fields should match source=firefox, kind=url_visit, project=domain."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"
    now = datetime.now(UTC)
    visit_time = now - timedelta(minutes=5)

    _insert_visit(db, "https://github.com/user/repo", "My Repo", visit_time)

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    events = firefox.fetch_since(now - timedelta(hours=1))

    assert len(events) == 1
    ev = events[0]
    assert ev.source == "firefox"
    assert ev.kind == "url_visit"
    assert ev.title == "My Repo"
    assert ev.project == "github.com"
    assert ev.url == "https://github.com/user/repo"


@pytest.mark.spec("firefox.F4")
def test_event_title_falls_back_to_url_when_no_title(tmp_path, monkeypatch):
    """When the page title is NULL, title should fall back to the URL."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"
    now = datetime.now(UTC)

    _insert_visit(db, "https://example.com/notitle", None, now - timedelta(minutes=5))

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    events = firefox.fetch_since(now - timedelta(hours=1))

    assert len(events) == 1
    assert events[0].title == "https://example.com/notitle"


# ---------------------------------------------------------------------------
# F5 — skips internal Firefox pages
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F5")
def test_skips_about_pages(tmp_path, monkeypatch):
    """URLs with scheme 'about:' should not produce events."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"
    now = datetime.now(UTC)

    _insert_visit(db, "about:newtab", "New Tab", now - timedelta(minutes=2))
    _insert_visit(db, "https://example.com", "Example", now - timedelta(minutes=1))

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    events = firefox.fetch_since(now - timedelta(hours=1))

    urls = [e.url for e in events]
    assert "about:newtab" not in urls
    assert "https://example.com" in urls


@pytest.mark.spec("firefox.F5")
def test_skips_moz_extension_pages(tmp_path, monkeypatch):
    """URLs with scheme 'moz-extension:' should not produce events."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"
    now = datetime.now(UTC)

    _insert_visit(db, "moz-extension://abc123/popup.html", "Popup", now - timedelta(minutes=2))
    _insert_visit(db, "https://example.com", "Example", now - timedelta(minutes=1))

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    events = firefox.fetch_since(now - timedelta(hours=1))

    urls = [e.url for e in events]
    assert not any("moz-extension" in u for u in urls)
    assert "https://example.com" in urls


# ---------------------------------------------------------------------------
# F6 — health_check False when no profile
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F6")
def test_health_check_false_when_no_profile(monkeypatch):
    """health_check should return False when no Firefox profile can be located."""
    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: None)

    firefox = Firefox()
    assert firefox.health_check() is False


@pytest.mark.spec("firefox.F6")
def test_health_check_true_when_profile_exists(tmp_path, monkeypatch):
    """health_check should return True when a places.sqlite is found."""
    profile = _fake_profile(tmp_path)
    db = profile / "places.sqlite"

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: db)

    firefox = Firefox()
    assert firefox.health_check() is True


# ---------------------------------------------------------------------------
# F7 — graceful handling when no profile found
# ---------------------------------------------------------------------------


@pytest.mark.spec("firefox.F7")
def test_fetch_since_returns_empty_when_no_profile(monkeypatch, caplog):
    """fetch_since should return [] and log a warning when no profile is found."""
    import logging

    monkeypatch.setattr("jarvis.integrations.firefox._places_path", lambda: None)

    firefox = Firefox()
    since = datetime.now(UTC) - timedelta(days=1)

    with caplog.at_level(logging.WARNING, logger="jarvis.integrations.firefox"):
        events = firefox.fetch_since(since)

    assert events == []
    assert any("no profile" in rec.message.lower() for rec in caplog.records)
