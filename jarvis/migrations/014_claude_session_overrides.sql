CREATE TABLE IF NOT EXISTS claude_session_overrides (
    session_id     TEXT PRIMARY KEY,
    display_title  TEXT,
    archived       INTEGER NOT NULL DEFAULT 0,
    manual_tags    TEXT NOT NULL DEFAULT '[]',
    removed_tags   TEXT NOT NULL DEFAULT '[]',
    auto_tags      TEXT NOT NULL DEFAULT '[]',
    pr_links       TEXT NOT NULL DEFAULT '[]',
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cso_archived ON claude_session_overrides(archived);
