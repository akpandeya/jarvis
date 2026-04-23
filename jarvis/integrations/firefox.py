from __future__ import annotations

import logging
import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from jarvis.integrations.base import RawEvent

logger = logging.getLogger(__name__)

# Microseconds per second — Firefox stores timestamps as µs since Unix epoch
_USEC = 1_000_000

# URL schemes that indicate internal Firefox pages to skip
_SKIP_SCHEMES = {"about", "moz-extension"}


def _profile_dir() -> Path | None:
    """Return the path to the first matching Firefox default-release profile, or None."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
    else:
        base = Path.home() / ".mozilla" / "firefox"

    if not base.exists():
        return None

    for candidate in sorted(base.iterdir()):
        if candidate.is_dir() and candidate.name.endswith(".default-release"):
            db = candidate / "places.sqlite"
            if db.exists():
                return candidate

    return None


def _places_path() -> Path | None:
    profile = _profile_dir()
    if profile is None:
        return None
    return profile / "places.sqlite"


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


class Firefox:
    name = "firefox"

    def health_check(self) -> bool:
        return _places_path() is not None

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        places = _places_path()
        if places is None:
            logger.warning("firefox: no profile found — skipping")
            return []

        since_usec = int(since.timestamp() * _USEC)

        # Copy to a temp file to avoid SQLite locked-database errors when Firefox is open
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            shutil.copy2(places, tmp_path)
            return self._read_events(tmp_path, since_usec)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _read_events(self, db_path: Path, since_usec: int) -> list[RawEvent]:
        events: list[RawEvent] = []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                    p.url,
                    p.title,
                    v.visit_date
                FROM moz_historyvisits AS v
                JOIN moz_places AS p ON p.id = v.place_id
                WHERE v.visit_date > ?
                ORDER BY v.visit_date ASC
                """,
                (since_usec,),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            url: str = row["url"] or ""
            title: str = row["title"] or ""
            visit_date_usec: int = row["visit_date"]

            # Skip internal Firefox pages (F5)
            scheme = urlparse(url).scheme
            if scheme in _SKIP_SCHEMES:
                continue

            happened_at = datetime.fromtimestamp(visit_date_usec / _USEC, tz=UTC)

            events.append(
                RawEvent(
                    source="firefox",
                    kind="url_visit",
                    title=title if title else url,
                    happened_at=happened_at,
                    url=url,
                    project=_domain(url),
                )
            )

        return events
