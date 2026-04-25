ALTER TABLE pr_subscriptions ADD COLUMN last_review_verdict TEXT;
ALTER TABLE pr_subscriptions ADD COLUMN last_review_must_fix INTEGER;
ALTER TABLE pr_subscriptions ADD COLUMN last_review_nits INTEGER;
ALTER TABLE pr_subscriptions ADD COLUMN last_review_at TEXT;
