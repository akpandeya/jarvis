"""Computer-wide activity collector.

Reads Firefox history, Thunderbird emails, shell history, and Jarvis CLI
commands into the activity_log table. Unlike integrations/* (which write to
events), this module writes to activity_log.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from jarvis.config import FirefoxConfig, JarvisConfig, ThunderbirdConfig
from jarvis.db import insert_activity

logger = logging.getLogger(__name__)

_SHELL_NOISE = {"ls", "cd", "clear", "pwd", "exit", "history", "man", "which"}


# ---------------------------------------------------------------------------
# CLI tracker — called directly from cli.py after each command
# ---------------------------------------------------------------------------


def record_cli(
    conn: sqlite3.Connection,
    command: str,
    args: list[str],
    project: str | None,
    duration_ms: int,
    exit_code: int,
) -> None:
    insert_activity(
        conn,
        source="jarvis_cli",
        kind="command",
        happened_at=datetime.now(UTC),
        title=command,
        body=json.dumps(args),
        metadata={"exit_code": exit_code, "duration_ms": duration_ms, "project": project},
    )


# ---------------------------------------------------------------------------
# Firefox
# ---------------------------------------------------------------------------

_PROFILE_NAME_RE = re.compile(r'user_pref\("browser\.profile\.name",\s*"([^"]+)"\)')
_FIREFOX_PROFILES = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"


def _firefox_profile_label(profile_dir: Path, config: FirefoxConfig) -> str:
    stem = profile_dir.name
    for override in config.profiles:
        if override.path == stem:
            return override.label
    prefs = profile_dir / "prefs.js"
    if prefs.exists():
        m = _PROFILE_NAME_RE.search(prefs.read_text(errors="replace"))
        if m:
            return m.group(1)
    return stem


def _open_firefox_db(db_path: Path) -> sqlite3.Connection | None:
    """Open places.sqlite, copying to a temp file if locked."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM moz_places LIMIT 1")
        return conn
    except sqlite3.OperationalError:
        pass
    # DB locked — copy and retry
    try:
        tmp = tempfile.mktemp(suffix=".sqlite")
        shutil.copy2(db_path, tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM moz_places LIMIT 1")
        conn._tmp_path = tmp  # type: ignore[attr-defined]
        return conn
    except Exception as e:
        logger.warning("firefox: could not open %s: %s", db_path, e)
        return None


def collect_firefox(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
    config: FirefoxConfig | None = None,
) -> int:
    if not _FIREFOX_PROFILES.exists():
        logger.warning("firefox: profiles directory not found")
        return 0

    cfg = config or FirefoxConfig()
    since_us = int(since.timestamp() * 1_000_000)
    until_us = int(until.timestamp() * 1_000_000) if until else None
    inserted = 0

    for profile_dir in _FIREFOX_PROFILES.iterdir():
        db_path = profile_dir / "places.sqlite"
        if not db_path.exists():
            continue

        label = _firefox_profile_label(profile_dir, cfg)
        ff_conn = _open_firefox_db(db_path)
        if ff_conn is None:
            continue

        try:
            query = (
                "SELECT p.url, p.title, v.visit_date "
                "FROM moz_places p JOIN moz_historyvisits v ON p.id = v.place_id "
                "WHERE v.visit_date > ?"
            )
            params: list = [since_us]
            if until_us:
                query += " AND v.visit_date <= ?"
                params.append(until_us)

            for row in ff_conn.execute(query, params):
                visit_dt = datetime.fromtimestamp(row["visit_date"] / 1_000_000, tz=UTC)
                ok = insert_activity(
                    conn,
                    source="firefox",
                    kind="page_visit",
                    happened_at=visit_dt,
                    title=row["title"] or row["url"],
                    url=row["url"],
                    metadata={"profile": label},
                )
                if ok:
                    inserted += 1
        except Exception as e:
            logger.warning("firefox: error reading %s: %s", profile_dir.name, e)
        finally:
            tmp = getattr(ff_conn, "_tmp_path", None)
            ff_conn.close()
            if tmp:
                Path(tmp).unlink(missing_ok=True)

    return inserted


# ---------------------------------------------------------------------------
# Thunderbird
# ---------------------------------------------------------------------------

_THUNDERBIRD_PROFILES = Path.home() / "Library" / "Thunderbird" / "Profiles"
_SPAM_FOLDERS = {"spam", "junk", "trash", "deleted items", "deleted"}


def _thunderbird_account(sender: str, work_domains: list[str]) -> str:
    if not work_domains:
        return "personal"
    domain = sender.split("@")[-1].lower() if "@" in sender else ""
    return "work" if domain in {d.lower() for d in work_domains} else "personal"


def collect_thunderbird(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
    config: ThunderbirdConfig | None = None,
) -> int:
    if not _THUNDERBIRD_PROFILES.exists():
        logger.warning("thunderbird: profiles directory not found")
        return 0

    cfg = config or ThunderbirdConfig()
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000) if until else None
    inserted = 0

    for profile_dir in _THUNDERBIRD_PROFILES.iterdir():
        db_path = profile_dir / "global-messages-db.sqlite"
        if not db_path.exists():
            continue
        try:
            tb_conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            tb_conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError as e:
            logger.warning("thunderbird: could not open %s: %s", db_path, e)
            continue

        try:
            query = (
                "SELECT subject, author, date, folderURI FROM messages "
                "WHERE date > ? AND (junkscore IS NULL OR junkscore < 50)"
            )
            params: list = [since_ms]
            if until_ms:
                query += " AND date <= ?"
                params.append(until_ms)

            for row in tb_conn.execute(query, params):
                folder = (row["folderURI"] or "").rstrip("/").split("/")[-1].lower()
                if folder in _SPAM_FOLDERS:
                    continue

                msg_dt = datetime.fromtimestamp(row["date"] / 1000, tz=UTC)
                sender = row["author"] or ""
                account = _thunderbird_account(sender, cfg.work_domains)
                ok = insert_activity(
                    conn,
                    source="thunderbird",
                    kind="email",
                    happened_at=msg_dt,
                    title=row["subject"] or "(no subject)",
                    body=sender,
                    metadata={"account": account},
                )
                if ok:
                    inserted += 1
        except Exception as e:
            logger.warning("thunderbird: error reading %s: %s", profile_dir.name, e)
        finally:
            tb_conn.close()

    return inserted


# ---------------------------------------------------------------------------
# Shell history
# ---------------------------------------------------------------------------


def collect_shell(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
) -> int:
    history_file = Path.home() / ".zsh_history"
    if not history_file.exists():
        logger.warning("shell: ~/.zsh_history not found")
        return 0

    since_ts = since.timestamp()
    until_ts = until.timestamp() if until else None
    inserted = 0
    seen: set[str] = set()

    try:
        raw = history_file.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        text = text.replace("\\\x1bE\n", " ").replace("\\\n", " ").replace("\x1b", "")
    except OSError as e:
        logger.warning("shell: could not read history: %s", e)
        return 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        ts_val: datetime | None = None
        if line.startswith(": "):
            m = re.match(r"^: (\d+):\d+;(.+)$", line)
            if not m:
                continue
            epoch = int(m.group(1))
            if epoch < since_ts:
                continue
            if until_ts and epoch > until_ts:
                continue
            ts_val = datetime.fromtimestamp(epoch, tz=UTC)
            cmd = m.group(2).strip()
        else:
            continue  # no timestamp — skip

        first_token = cmd.split()[0] if cmd.split() else ""
        if first_token in _SHELL_NOISE:
            continue

        key = f"{ts_val.isoformat()}:{cmd[:120]}"
        if key in seen:
            continue
        seen.add(key)

        ok = insert_activity(
            conn,
            source="shell",
            kind="shell_cmd",
            happened_at=ts_val,
            title=cmd[:500],
        )
        if ok:
            inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# collect_all
# ---------------------------------------------------------------------------


def collect_all(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
    config: JarvisConfig | None = None,
) -> dict[str, int]:
    cfg = config or JarvisConfig.load()
    counts: dict[str, int] = {}

    for name, fn, kwargs in [
        ("firefox", collect_firefox, {"config": cfg.firefox}),
        ("thunderbird", collect_thunderbird, {"config": cfg.thunderbird}),
        ("shell", collect_shell, {}),
    ]:
        try:
            n = fn(conn, since, until, **kwargs)  # type: ignore[operator]
            counts[name] = n
        except Exception as e:
            logger.warning("%s collector failed: %s", name, e)
            counts[name] = 0
        logger.info("%s: %d new rows", name, counts[name])

    return counts
