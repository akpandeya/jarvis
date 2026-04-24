CREATE TABLE IF NOT EXISTS jira_board_subs (
    id           TEXT PRIMARY KEY,
    host         TEXT NOT NULL,
    project_key  TEXT NOT NULL,
    board_id     INTEGER NOT NULL,
    nickname     TEXT NOT NULL,
    added_at     TEXT NOT NULL,
    UNIQUE(host, board_id)
);
