-- Phase 6: activity tracking and suggestion engine

CREATE TABLE IF NOT EXISTS activity_log (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,        -- jarvis_cli | firefox | thunderbird | shell
    kind        TEXT NOT NULL,        -- command | page_visit | email | shell_cmd
    title       TEXT,
    body        TEXT,
    url         TEXT,
    happened_at TEXT NOT NULL,        -- ISO 8601 UTC
    metadata    TEXT                  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_activity_time   ON activity_log(happened_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_source ON activity_log(source);

CREATE TABLE IF NOT EXISTS suggestions (
    id            TEXT PRIMARY KEY,
    rule_id       TEXT NOT NULL UNIQUE,  -- one active row per rule
    message       TEXT NOT NULL,
    action        TEXT,
    priority      INTEGER DEFAULT 50,
    created_at    TEXT NOT NULL,
    snoozed_until TEXT,
    dismissed     INTEGER DEFAULT 0
);
