-- Add deduplication constraint to activity_log

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_dedup
    ON activity_log(source, kind, happened_at);
