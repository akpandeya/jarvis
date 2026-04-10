from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ulid import ULID

from jarvis.config import DB_PATH
from jarvis.models import Event


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create all tables from the migration file."""
    conn = _connect(db_path)
    migration = Path(__file__).parent.parent / "migrations" / "001_initial.sql"
    conn.executescript(migration.read_text())
    conn.close()


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a connection, initializing the DB if needed."""
    path = db_path or DB_PATH
    if not path.exists():
        init_db(path)
    return _connect(path)


def upsert_event(
    conn: sqlite3.Connection,
    source: str,
    kind: str,
    title: str,
    happened_at: datetime,
    body: str | None = None,
    metadata: dict | None = None,
    url: str | None = None,
    project: str | None = None,
) -> str:
    """Insert or ignore an event. Returns the event ID."""
    event_id = str(ULID())
    meta_json = json.dumps(metadata) if metadata else None
    conn.execute(
        """INSERT OR IGNORE INTO events
           (id, source, kind, title, body, metadata, url, happened_at, project)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, source, kind, title, body, meta_json, url, happened_at.isoformat(), project),
    )
    conn.commit()
    return event_id


def upsert_entity(
    conn: sqlite3.Connection,
    kind: str,
    name: str,
    aliases: list[str] | None = None,
    metadata: dict | None = None,
) -> str:
    """Insert or update an entity. Returns the entity ID."""
    row = conn.execute(
        "SELECT id FROM entities WHERE kind = ? AND name = ?", (kind, name)
    ).fetchone()
    if row:
        return row["id"]
    entity_id = str(ULID())
    conn.execute(
        "INSERT INTO entities (id, kind, name, aliases, metadata) VALUES (?, ?, ?, ?, ?)",
        (
            entity_id,
            kind,
            name,
            json.dumps(aliases) if aliases else None,
            json.dumps(metadata) if metadata else None,
        ),
    )
    conn.commit()
    return entity_id


def link_event_entity(conn: sqlite3.Connection, event_id: str, entity_id: str, role: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) VALUES (?, ?, ?)",
        (event_id, entity_id, role),
    )
    conn.commit()


def query_events(
    conn: sqlite3.Connection,
    source: str | None = None,
    project: str | None = None,
    days: int = 7,
    limit: int = 50,
) -> list[Event]:
    """Query events with optional filters."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conditions = ["happened_at >= ?"]
    params: list[str | int] = [since]

    if source:
        conditions.append("source = ?")
        params.append(source)
    if project:
        conditions.append("project = ?")
        params.append(project)

    where = " AND ".join(conditions)
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM events WHERE {where} ORDER BY happened_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [Event.from_row(dict(r)) for r in rows]


def search_events(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[Event]:
    """Full-text search across events."""
    rows = conn.execute(
        """SELECT e.* FROM events e
           JOIN events_fts fts ON e.rowid = fts.rowid
           WHERE events_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [Event.from_row(dict(r)) for r in rows]


def event_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
    return row["cnt"]


# --- Sessions ---


def save_session(
    conn: sqlite3.Connection,
    context: str,
    project: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> str:
    """Save a session memory snapshot."""
    session_id = str(ULID())
    now = datetime.now()
    conn.execute(
        "INSERT INTO sessions (id, project, started_at, ended_at, context) VALUES (?, ?, ?, ?, ?)",
        (
            session_id,
            project,
            (started_at or now).isoformat(),
            (ended_at or now).isoformat(),
            context,
        ),
    )
    conn.commit()
    return session_id


def list_sessions(
    conn: sqlite3.Connection,
    project: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """List recent sessions."""
    if project:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE project = ? ORDER BY started_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
