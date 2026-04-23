from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent

# Glob patterns to find the Thunderbird profile directory
_PROFILE_GLOBS: list[tuple[Path, str]] = [
    (Path.home() / "Library" / "Thunderbird" / "Profiles", "*.default*"),  # macOS
    (Path.home() / ".thunderbird", "*.default*"),  # Linux
]

_DB_NAME = "global-messages-db.sqlite"


def _find_profile_db() -> Path | None:
    """Return path to global-messages-db.sqlite in the first matching Thunderbird profile."""
    for base, pattern in _PROFILE_GLOBS:
        if not base.exists():
            continue
        for profile_dir in sorted(base.glob(pattern)):
            candidate = profile_dir / _DB_NAME
            if candidate.exists():
                return candidate
    return None


def _extract_domain(email_field: str) -> str:
    """Extract the domain part from an email address string like 'Name <addr@domain.com>'."""
    match = re.search(r"[\w.+-]+@([\w.-]+)", email_field or "")
    if match:
        return match.group(1)
    return ""


class Thunderbird:
    name = "thunderbird"

    def health_check(self) -> bool:
        db_path = _find_profile_db()
        return db_path is not None

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        db_path = _find_profile_db()
        if db_path is None:
            return []

        # Convert since to a Unix timestamp (seconds). Thunderbird stores date in seconds.
        if since.tzinfo is None:
            since_ts = since.replace(tzinfo=UTC).timestamp()
        else:
            since_ts = since.timestamp()

        # Copy the DB to a temp file to avoid issues with a locked live database.
        try:
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            shutil.copy2(db_path, tmp_path)
        except OSError:
            return []

        events: list[RawEvent] = []
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT m.date, m.subject, m.author, m.recipients, fl.folderURI
                    FROM messages m
                    JOIN folderLocations fl ON m.folderID = fl.id
                    WHERE m.date >= ?
                    """,
                    (since_ts,),
                ).fetchall()
            except sqlite3.DatabaseError:
                return []
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return []
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        for row in rows:
            subject: str = (row["subject"] or "").strip()
            author: str = (row["author"] or "").strip()
            folder_uri: str = row["folderURI"] or ""

            # F6: skip empty drafts (no subject and no body — body not in messages table,
            # so we treat missing subject + missing author as a proxy for an empty draft)
            if not subject and not author:
                continue

            kind = "email_sent" if "Sent" in folder_uri else "email_received"
            domain = _extract_domain(author)

            # Build happened_at from the epoch seconds stored in Thunderbird
            happened_at = datetime.fromtimestamp(row["date"], tz=UTC)

            events.append(
                RawEvent(
                    source="thunderbird",
                    kind=kind,
                    title=subject or "(no subject)",
                    happened_at=happened_at,
                    project=domain or None,
                    metadata={
                        "author": author,
                        "recipients": row["recipients"],
                        "folder_uri": folder_uri,
                    },
                )
            )

        return events
