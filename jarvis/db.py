from __future__ import annotations

import json
import sqlite3

# Forward-declared here to avoid circular imports at the call site
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ulid import ULID

from jarvis.config import DB_PATH
from jarvis.models import Event


@dataclass
class Suggestion:
    rule_id: str
    message: str
    action: str
    priority: int


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Run all migrations in order."""
    conn = _connect(db_path)
    # Prefer bundled migrations (works in wheel installs); fall back to repo root
    pkg_migrations = Path(__file__).parent / "migrations"
    repo_migrations = Path(__file__).parent.parent / "migrations"
    migrations_dir = pkg_migrations if pkg_migrations.exists() else repo_migrations
    for migration in sorted(migrations_dir.glob("*.sql")):
        try:
            conn.executescript(migration.read_text())
        except sqlite3.OperationalError as e:
            # Tolerate "duplicate column" from ALTER TABLE on already-migrated DBs
            if "duplicate column" not in str(e):
                raise
    conn.close()


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a connection, running any pending migrations."""
    path = db_path or DB_PATH
    init_db(path)  # migrations use IF NOT EXISTS — safe to run every time
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


# --- Activity log ---


def insert_activity(
    conn: sqlite3.Connection,
    source: str,
    kind: str,
    happened_at: datetime,
    title: str | None = None,
    body: str | None = None,
    url: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Insert an activity row. Returns True if a new row was inserted."""
    row_id = str(ULID())
    meta_json = json.dumps(metadata) if metadata else None
    cursor = conn.execute(
        """INSERT OR IGNORE INTO activity_log
           (id, source, kind, title, body, url, happened_at, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (row_id, source, kind, title, body, url, happened_at.isoformat(), meta_json),
    )
    conn.commit()
    return cursor.rowcount == 1


def query_activity(
    conn: sqlite3.Connection,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> list[dict]:
    conditions = []
    params: list = []
    if source:
        conditions.append("source = ?")
        params.append(source)
    if since:
        conditions.append("happened_at >= ?")
        params.append(since.isoformat())
    if until:
        conditions.append("happened_at <= ?")
        params.append(until.isoformat())
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM activity_log {where} ORDER BY happened_at DESC LIMIT ?", params
    ).fetchall()
    return [dict(r) for r in rows]


def command_frequency(conn: sqlite3.Connection, limit: int = 10) -> list[tuple[str, int]]:
    """Return top CLI commands by frequency from activity_log."""
    rows = conn.execute(
        """SELECT title, COUNT(*) as cnt FROM activity_log
           WHERE source='jarvis_cli'
           GROUP BY title ORDER BY cnt DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [(r["title"], r["cnt"]) for r in rows]


def top_urls(conn: sqlite3.Connection, limit: int = 10) -> list[tuple[str, int]]:
    """Return top URL domains from Firefox events, ordered by visit count."""
    rows = conn.execute(
        """SELECT url, COUNT(*) as cnt FROM events
           WHERE source='firefox' AND url IS NOT NULL
           GROUP BY url ORDER BY cnt DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    # Extract domain from URL
    from urllib.parse import urlparse

    domain_counts: dict[str, int] = {}
    for r in rows:
        try:
            domain = urlparse(r["url"]).netloc or r["url"]
        except Exception:
            domain = r["url"]
        domain_counts[domain] = domain_counts.get(domain, 0) + r["cnt"]
    # Re-sort and limit
    sorted_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return sorted_domains


def source_distribution(conn: sqlite3.Connection, days: int = 30) -> dict[str, int]:
    """Return event count per source for the last N days."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT source, COUNT(*) as cnt FROM events
           WHERE happened_at >= ?
           GROUP BY source ORDER BY cnt DESC""",
        (since,),
    ).fetchall()
    return {r["source"]: r["cnt"] for r in rows}


# --- Suggestions ---


def upsert_suggestion(conn: sqlite3.Connection, suggestion: Suggestion) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO suggestions (id, rule_id, message, action, priority, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(rule_id) DO UPDATE SET
               message=excluded.message,
               action=excluded.action,
               priority=excluded.priority""",
        (
            str(ULID()),
            suggestion.rule_id,
            suggestion.message,
            suggestion.action,
            suggestion.priority,
            now,
        ),
    )
    conn.commit()


def get_pending_suggestions(conn: sqlite3.Connection) -> list[Suggestion]:
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(
        """SELECT rule_id, message, action, priority FROM suggestions
           WHERE dismissed = 0
             AND (snoozed_until IS NULL OR snoozed_until < ?)
           ORDER BY priority DESC""",
        (now,),
    ).fetchall()
    return [Suggestion(**dict(r)) for r in rows]


def dismiss_suggestion(conn: sqlite3.Connection, rule_id: str) -> None:
    conn.execute("UPDATE suggestions SET dismissed = 1 WHERE rule_id = ?", (rule_id,))
    conn.commit()


def clear_suggestion(conn: sqlite3.Connection, rule_id: str) -> None:
    """Delete the suggestion row so it can re-fire when the rule triggers again."""
    conn.execute("DELETE FROM suggestions WHERE rule_id = ?", (rule_id,))
    conn.commit()


def snooze_suggestion(conn: sqlite3.Connection, rule_id: str, until: datetime) -> None:
    conn.execute(
        "UPDATE suggestions SET snoozed_until = ? WHERE rule_id = ?",
        (until.isoformat(), rule_id),
    )
    conn.commit()


# --- Key-value store ---


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def kv_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


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


# --- Repo paths ---


def list_repo_paths(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM repo_paths ORDER BY added_at DESC").fetchall()
    return [dict(r) for r in rows]


def add_repo_path(conn: sqlite3.Connection, path: str) -> str:
    row_id = str(ULID())
    conn.execute(
        "INSERT OR IGNORE INTO repo_paths (id, path, added_at) VALUES (?, ?, ?)",
        (row_id, path, datetime.now().isoformat()),
    )
    conn.commit()
    return row_id


def delete_repo_path(conn: sqlite3.Connection, path_id: str) -> None:
    conn.execute("DELETE FROM repo_paths WHERE id = ?", (path_id,))
    conn.commit()


def set_repo_path_account(conn: sqlite3.Connection, path_id: str, gh_account: str | None) -> None:
    conn.execute("UPDATE repo_paths SET gh_account=? WHERE id=?", (gh_account, path_id))
    conn.commit()


def set_repo_path_enabled(conn: sqlite3.Connection, path_id: str, enabled: bool) -> None:
    conn.execute("UPDATE repo_paths SET enabled=? WHERE id=?", (1 if enabled else 0, path_id))
    conn.commit()
