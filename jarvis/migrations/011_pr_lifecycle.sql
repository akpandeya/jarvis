ALTER TABLE pr_subscriptions ADD COLUMN watch_state TEXT NOT NULL DEFAULT 'watching';
ALTER TABLE pr_subscriptions ADD COLUMN chat_session_id TEXT;

-- Backfill: only fix dismissed=1 rows that haven't been migrated yet
UPDATE pr_subscriptions SET watch_state = 'dismissed' WHERE dismissed=1 AND watch_state='watching';
