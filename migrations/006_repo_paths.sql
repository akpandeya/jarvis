CREATE TABLE IF NOT EXISTS repo_paths (
    id       TEXT PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);
