ALTER TABLE pr_subscriptions ADD COLUMN watch_state TEXT NOT NULL DEFAULT 'watching';
ALTER TABLE pr_subscriptions ADD COLUMN chat_session_id TEXT;

-- Backfill: dismissed rows → 'dismissed', everything else → 'watching'
UPDATE pr_subscriptions SET watch_state = CASE WHEN dismissed=1 THEN 'dismissed' ELSE 'watching' END;
