CREATE TABLE IF NOT EXISTS pr_subscriptions (
    id             TEXT PRIMARY KEY,
    repo           TEXT NOT NULL,
    pr_number      INTEGER NOT NULL,
    title          TEXT,
    author         TEXT,
    branch         TEXT,
    pr_url         TEXT,
    state          TEXT NOT NULL DEFAULT 'open',
    subscribed_at  TEXT NOT NULL,
    last_fetched_at TEXT,
    UNIQUE(repo, pr_number)
);
