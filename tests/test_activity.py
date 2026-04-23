"""Tests for jarvis/activity.py — keyed to docs/specs/activity_tracker.md."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.activity import (
    _firefox_profile_label,
    _thunderbird_account,
    collect_firefox,
    collect_shell,
    collect_thunderbird,
    record_cli,
)
from jarvis.config import FirefoxConfig, FirefoxProfileConfig


def _now():
    return datetime.now(UTC)


def _since():
    return _now() - timedelta(hours=1)


# ---------------------------------------------------------------------------
# record_cli
# ---------------------------------------------------------------------------


@pytest.mark.spec("activity_tracker.F1")
def test_record_cli_inserts_row(db):
    record_cli(
        db, command="standup", args=["--days", "1"], project="jarvis", duration_ms=200, exit_code=0
    )
    rows = db.execute("SELECT * FROM activity_log WHERE source='jarvis_cli'").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "standup"


@pytest.mark.spec("activity_tracker.F1")
def test_record_cli_stores_metadata(db):
    record_cli(db, command="ingest", args=[], project=None, duration_ms=500, exit_code=1)
    row = db.execute("SELECT metadata FROM activity_log WHERE source='jarvis_cli'").fetchone()
    meta = json.loads(row["metadata"])
    assert meta["exit_code"] == 1
    assert meta["duration_ms"] == 500


# ---------------------------------------------------------------------------
# Firefox profile label resolution
# ---------------------------------------------------------------------------


@pytest.mark.spec("activity_tracker.F3")
def test_firefox_profile_label_config_override(tmp_path):
    profile_dir = tmp_path / "abc123.default-release"
    profile_dir.mkdir()
    cfg = FirefoxConfig(
        profiles=[FirefoxProfileConfig(path="abc123.default-release", label="Work")]
    )
    assert _firefox_profile_label(profile_dir, cfg) == "Work"


@pytest.mark.spec("activity_tracker.F3")
def test_firefox_profile_label_from_prefs(tmp_path):
    profile_dir = tmp_path / "xyz.default"
    profile_dir.mkdir()
    (profile_dir / "prefs.js").write_text('user_pref("browser.profile.name", "Personal");\n')
    cfg = FirefoxConfig()
    assert _firefox_profile_label(profile_dir, cfg) == "Personal"


@pytest.mark.spec("activity_tracker.F3")
def test_firefox_profile_label_falls_back_to_stem(tmp_path):
    profile_dir = tmp_path / "fallback.default"
    profile_dir.mkdir()
    cfg = FirefoxConfig()
    assert _firefox_profile_label(profile_dir, cfg) == "fallback.default"


# ---------------------------------------------------------------------------
# Firefox collection
# ---------------------------------------------------------------------------


def _make_firefox_profile(base: Path, profile_name: str, visits: list[tuple]) -> Path:
    """Create a minimal places.sqlite with given visits: [(url, title, visit_date_us)]."""
    profile_dir = base / profile_name
    profile_dir.mkdir(parents=True)
    conn = sqlite3.connect(str(profile_dir / "places.sqlite"))
    conn.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE moz_historyvisits "
        "(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)"
    )
    for i, (url, title, visit_us) in enumerate(visits):
        conn.execute("INSERT INTO moz_places VALUES (?, ?, ?)", (i + 1, url, title))
        conn.execute("INSERT INTO moz_historyvisits VALUES (?, ?, ?)", (i + 1, i + 1, visit_us))
    conn.commit()
    conn.close()
    return profile_dir


@pytest.mark.spec("activity_tracker.F2")
def test_collect_firefox_inserts_recent_visits(db, tmp_path, monkeypatch):
    since = _now() - timedelta(minutes=30)
    visit_us = int(_now().timestamp() * 1_000_000)
    _make_firefox_profile(tmp_path, "p1", [("https://example.com", "Example", visit_us)])
    monkeypatch.setattr("jarvis.activity._FIREFOX_PROFILES", tmp_path)
    count = collect_firefox(db, since)
    assert count == 1
    row = db.execute("SELECT url FROM activity_log WHERE source='firefox'").fetchone()
    assert row["url"] == "https://example.com"


@pytest.mark.spec("activity_tracker.F2")
def test_collect_firefox_skips_old_visits(db, tmp_path, monkeypatch):
    since = _now()
    old_us = int((_now() - timedelta(hours=2)).timestamp() * 1_000_000)
    _make_firefox_profile(tmp_path, "p1", [("https://old.com", "Old", old_us)])
    monkeypatch.setattr("jarvis.activity._FIREFOX_PROFILES", tmp_path)
    count = collect_firefox(db, since)
    assert count == 0


@pytest.mark.spec("activity_tracker.F2")
def test_collect_firefox_missing_profiles_dir(db, tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.activity._FIREFOX_PROFILES", tmp_path / "nonexistent")
    count = collect_firefox(db, _since())
    assert count == 0


# ---------------------------------------------------------------------------
# Thunderbird account classification
# ---------------------------------------------------------------------------


@pytest.mark.spec("activity_tracker.F5")
def test_thunderbird_account_work(db):
    assert _thunderbird_account("alice@company.com", ["company.com"]) == "work"


@pytest.mark.spec("activity_tracker.F5")
def test_thunderbird_account_personal(db):
    assert _thunderbird_account("bob@gmail.com", ["company.com"]) == "personal"


@pytest.mark.spec("activity_tracker.F11")
def test_thunderbird_account_no_domains_is_personal(db):
    assert _thunderbird_account("anyone@anywhere.com", []) == "personal"


# ---------------------------------------------------------------------------
# Thunderbird collection
# ---------------------------------------------------------------------------


def _make_thunderbird_db(base: Path, messages: list[dict]) -> Path:
    """Create a minimal global-messages-db.sqlite."""
    profile_dir = base / "profile.default"
    profile_dir.mkdir(parents=True)
    conn = sqlite3.connect(str(profile_dir / "global-messages-db.sqlite"))
    conn.execute(
        """CREATE TABLE messages (
            id INTEGER PRIMARY KEY, subject TEXT, author TEXT,
            date INTEGER, folderURI TEXT, junkscore INTEGER
        )"""
    )
    for i, m in enumerate(messages):
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            (i + 1, m["subject"], m["author"], m["date"], m["folderURI"], m.get("junkscore", 0)),
        )
    conn.commit()
    conn.close()
    return profile_dir


@pytest.mark.spec("activity_tracker.F4")
def test_collect_thunderbird_inserts_email(db, tmp_path, monkeypatch):
    since = _now() - timedelta(minutes=10)
    date_ms = int(_now().timestamp() * 1000)
    _make_thunderbird_db(
        tmp_path,
        [
            {
                "subject": "Hello",
                "author": "alice@corp.com",
                "date": date_ms,
                "folderURI": "imap://inbox",
            }
        ],
    )
    monkeypatch.setattr("jarvis.activity._THUNDERBIRD_PROFILES", tmp_path)
    count = collect_thunderbird(db, since)
    assert count == 1


@pytest.mark.spec("activity_tracker.F13")
def test_collect_thunderbird_skips_spam_folder(db, tmp_path, monkeypatch):
    since = _now() - timedelta(minutes=10)
    date_ms = int(_now().timestamp() * 1000)
    _make_thunderbird_db(
        tmp_path,
        [
            {
                "subject": "Buy now!",
                "author": "spam@spam.com",
                "date": date_ms,
                "folderURI": "imap://spam",
            }
        ],
    )
    monkeypatch.setattr("jarvis.activity._THUNDERBIRD_PROFILES", tmp_path)
    count = collect_thunderbird(db, since)
    assert count == 0


@pytest.mark.spec("activity_tracker.F13")
def test_collect_thunderbird_skips_high_junkscore(db, tmp_path, monkeypatch):
    since = _now() - timedelta(minutes=10)
    date_ms = int(_now().timestamp() * 1000)
    _make_thunderbird_db(
        tmp_path,
        [
            {
                "subject": "Junk",
                "author": "x@x.com",
                "date": date_ms,
                "folderURI": "imap://inbox",
                "junkscore": 80,
            }
        ],
    )
    monkeypatch.setattr("jarvis.activity._THUNDERBIRD_PROFILES", tmp_path)
    count = collect_thunderbird(db, since)
    assert count == 0


# ---------------------------------------------------------------------------
# Shell collection
# ---------------------------------------------------------------------------


def _write_history(path: Path, entries: list[tuple[int, str]]) -> None:
    """Write zsh extended history format: ': epoch:0;command'."""
    lines = [f": {ts}:0;{cmd}" for ts, cmd in entries]
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.spec("activity_tracker.F6")
def test_collect_shell_inserts_commands(db, tmp_path, monkeypatch):
    history = tmp_path / ".zsh_history"
    epoch = int(_now().timestamp())
    _write_history(history, [(epoch, "git status")])
    monkeypatch.setattr("jarvis.activity.Path.home", lambda: tmp_path)
    since = _now() - timedelta(minutes=5)
    count = collect_shell(db, since)
    assert count == 1


@pytest.mark.spec("activity_tracker.F7")
def test_collect_shell_skips_noise_commands(db, tmp_path, monkeypatch):
    history = tmp_path / ".zsh_history"
    epoch = int(_now().timestamp())
    _write_history(history, [(epoch, "ls"), (epoch + 1, "cd /tmp"), (epoch + 2, "clear")])
    monkeypatch.setattr("jarvis.activity.Path.home", lambda: tmp_path)
    since = _now() - timedelta(minutes=5)
    count = collect_shell(db, since)
    assert count == 0


@pytest.mark.spec("activity_tracker.F6")
def test_collect_shell_skips_lines_without_timestamp(db, tmp_path, monkeypatch):
    history = tmp_path / ".zsh_history"
    history.write_text("git log --oneline\n")  # no ': epoch:0;' prefix
    monkeypatch.setattr("jarvis.activity.Path.home", lambda: tmp_path)
    since = _now() - timedelta(minutes=5)
    count = collect_shell(db, since)
    assert count == 0
