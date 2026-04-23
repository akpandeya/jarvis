from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.integrations.thunderbird import Thunderbird

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gloda_db(path: Path) -> None:
    """Create a minimal global-messages-db.sqlite matching the gloda schema."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE folderLocations (
            id INTEGER PRIMARY KEY,
            folderURI TEXT NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            folderID INTEGER NOT NULL,
            messageKey INTEGER,
            date REAL NOT NULL,
            subject TEXT,
            author TEXT,
            recipients TEXT,
            read INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_message(
    db: Path,
    folder_uri: str,
    date_epoch: float,
    subject: str | None = "Test subject",
    author: str | None = "Alice <alice@example.com>",
    recipients: str | None = "Bob <bob@work.com>",
) -> None:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    # Upsert folder
    cur.execute("INSERT OR IGNORE INTO folderLocations (folderURI) VALUES (?)", (folder_uri,))
    cur.execute("SELECT id FROM folderLocations WHERE folderURI = ?", (folder_uri,))
    folder_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO messages (folderID, date, subject, author, recipients) VALUES (?,?,?,?,?)",
        (folder_id, date_epoch, subject, author, recipients),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_profile(tmp_path: Path) -> Path:
    """Return a fake macOS-style Thunderbird profile directory with an empty DB."""
    profiles_dir = tmp_path / "Library" / "Thunderbird" / "Profiles"
    profile = profiles_dir / "abc123.default-release"
    profile.mkdir(parents=True)
    db = profile / "global-messages-db.sqlite"
    _make_gloda_db(db)
    return tmp_path


@pytest.fixture()
def thunderbird(fake_profile: Path) -> tuple[Thunderbird, Path]:
    """Return (Thunderbird instance, db path) with the profile search patched."""
    db = (
        fake_profile
        / "Library"
        / "Thunderbird"
        / "Profiles"
        / "abc123.default-release"
        / "global-messages-db.sqlite"
    )
    return Thunderbird(), db


# ---------------------------------------------------------------------------
# F1 — finds profile
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F1")
def test_finds_profile(fake_profile: Path) -> None:
    """health_check returns True when a valid profile DB exists."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        tb = Thunderbird()
        assert tb.health_check() is True


# ---------------------------------------------------------------------------
# F2 — copies DB before reading
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F2")
def test_copies_db_before_reading(fake_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_since copies the database to a temp file; the original is not opened directly."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"
    db = profiles_dir / "abc123.default-release" / "global-messages-db.sqlite"

    copy_calls: list[tuple] = []
    real_copy2 = shutil.copy2

    def spy_copy2(src, dst, **kwargs):
        copy_calls.append((src, dst))
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", spy_copy2)

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        tb = Thunderbird()
        tb.fetch_since(datetime(2020, 1, 1, tzinfo=UTC))

    assert len(copy_calls) == 1
    assert Path(copy_calls[0][0]) == db


# ---------------------------------------------------------------------------
# F3 — only fetches messages since cutoff
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F3")
def test_fetches_only_since_cutoff(fake_profile: Path) -> None:
    """Messages with date < since are excluded; messages >= since are included."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"
    db = profiles_dir / "abc123.default-release" / "global-messages-db.sqlite"

    now = time.time()
    old_ts = now - 7200  # 2 hours ago
    recent_ts = now - 300  # 5 minutes ago
    cutoff_ts = now - 600  # 10 minutes ago

    _insert_message(db, "imap://host/INBOX", old_ts, subject="Old message")
    _insert_message(db, "imap://host/INBOX", recent_ts, subject="Recent message")

    cutoff = datetime.fromtimestamp(cutoff_ts, tz=UTC)

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        events = Thunderbird().fetch_since(cutoff)

    titles = [e.title for e in events]
    assert "Recent message" in titles
    assert "Old message" not in titles


# ---------------------------------------------------------------------------
# F4 — email_sent vs email_received
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F4")
def test_email_sent_vs_received(fake_profile: Path) -> None:
    """Messages in Sent folders get kind='email_sent'; others get 'email_received'."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"
    db = profiles_dir / "abc123.default-release" / "global-messages-db.sqlite"

    now = time.time()
    _insert_message(db, "imap://host/Sent", now, subject="Sent email")
    _insert_message(db, "imap://host/INBOX", now, subject="Received email")

    cutoff = datetime.fromtimestamp(now - 60, tz=UTC)

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        events = Thunderbird().fetch_since(cutoff)

    by_title = {e.title: e for e in events}
    assert by_title["Sent email"].kind == "email_sent"
    assert by_title["Received email"].kind == "email_received"


# ---------------------------------------------------------------------------
# F5 — subject as title, domain as project
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F5")
def test_subject_and_domain(fake_profile: Path) -> None:
    """Event title equals the email subject; project equals the sender domain."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"
    db = profiles_dir / "abc123.default-release" / "global-messages-db.sqlite"

    now = time.time()
    _insert_message(
        db,
        "imap://host/INBOX",
        now,
        subject="Sprint planning",
        author="Carol <carol@acme.org>",
    )

    cutoff = datetime.fromtimestamp(now - 60, tz=UTC)

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        events = Thunderbird().fetch_since(cutoff)

    assert len(events) == 1
    assert events[0].title == "Sprint planning"
    assert events[0].project == "acme.org"


# ---------------------------------------------------------------------------
# F6 — skips empty drafts
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F6")
def test_skips_empty_drafts(fake_profile: Path) -> None:
    """Messages with no subject AND no author are skipped."""
    profiles_dir = fake_profile / "Library" / "Thunderbird" / "Profiles"
    db = profiles_dir / "abc123.default-release" / "global-messages-db.sqlite"

    now = time.time()
    # Empty draft — no subject, no author
    _insert_message(db, "imap://host/Drafts", now, subject=None, author=None)
    # Real message — has subject
    _insert_message(db, "imap://host/INBOX", now, subject="Real email", author="Dave <dave@x.io>")

    cutoff = datetime.fromtimestamp(now - 60, tz=UTC)

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(profiles_dir, "*.default*")]):
        events = Thunderbird().fetch_since(cutoff)

    assert len(events) == 1
    assert events[0].title == "Real email"


# ---------------------------------------------------------------------------
# F7 — health_check False when no profile
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F7")
def test_health_check_false_when_no_profile(tmp_path: Path) -> None:
    """health_check returns False when no Thunderbird profile with the DB can be found."""
    empty_dir = tmp_path / "no_profiles"
    empty_dir.mkdir()

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(empty_dir, "*.default*")]):
        tb = Thunderbird()
        assert tb.health_check() is False


# ---------------------------------------------------------------------------
# F8 — handles missing/locked DB gracefully
# ---------------------------------------------------------------------------


@pytest.mark.spec("thunderbird.F8")
def test_returns_empty_on_missing_db(tmp_path: Path) -> None:
    """fetch_since returns [] when the DB cannot be found, without raising."""
    empty_dir = tmp_path / "no_profiles"
    empty_dir.mkdir()

    with patch("jarvis.integrations.thunderbird._PROFILE_GLOBS", [(empty_dir, "*.default*")]):
        events = Thunderbird().fetch_since(datetime(2020, 1, 1, tzinfo=UTC))

    assert events == []
