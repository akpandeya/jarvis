-- Jarvis initial schema

CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT,
    metadata    TEXT,
    url         TEXT,
    happened_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    project     TEXT,
    UNIQUE(source, kind, url)
);

CREATE INDEX IF NOT EXISTS idx_events_time ON events(happened_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source, kind);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title, body, content=events, content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
    INSERT INTO events_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;

CREATE TABLE IF NOT EXISTS entities (
    id       TEXT PRIMARY KEY,
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    aliases  TEXT,
    metadata TEXT,
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS event_entities (
    event_id  TEXT REFERENCES events(id),
    entity_id TEXT REFERENCES entities(id),
    role      TEXT,
    PRIMARY KEY (event_id, entity_id, role)
);

CREATE TABLE IF NOT EXISTS entity_links (
    from_id  TEXT REFERENCES entities(id),
    to_id    TEXT REFERENCES entities(id),
    relation TEXT NOT NULL,
    metadata TEXT,
    PRIMARY KEY (from_id, to_id, relation)
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    project    TEXT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    context    TEXT NOT NULL,
    raw_events TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    scope        TEXT,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    content      TEXT NOT NULL,
    event_ids    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    model        TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
