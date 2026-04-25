-- Claude session events inserted before url was stable were duplicated on
-- every ingest because the upsert key (source, kind, url) tolerates NULL url.
-- Keep only the row with the latest last_message_at per session_id, then
-- backfill the url so future upserts actually update.

DELETE FROM event_entities
WHERE event_id IN (
    SELECT id FROM events
    WHERE source = 'claude_sessions'
      AND id NOT IN (
          SELECT id FROM (
              SELECT id,
                     ROW_NUMBER() OVER (
                         PARTITION BY json_extract(metadata,'$.session_id')
                         ORDER BY COALESCE(json_extract(metadata,'$.last_message_at'), happened_at) DESC
                     ) AS rn
              FROM events
              WHERE source = 'claude_sessions'
          )
          WHERE rn = 1
      )
);

DELETE FROM events
WHERE source = 'claude_sessions'
  AND id NOT IN (
      SELECT id FROM (
          SELECT id,
                 ROW_NUMBER() OVER (
                     PARTITION BY json_extract(metadata,'$.session_id')
                     ORDER BY COALESCE(json_extract(metadata,'$.last_message_at'), happened_at) DESC
                 ) AS rn
          FROM events
          WHERE source = 'claude_sessions'
      )
      WHERE rn = 1
  );

UPDATE events
SET url = 'claude-session://' || json_extract(metadata,'$.session_id')
WHERE source = 'claude_sessions'
  AND url IS NULL
  AND json_extract(metadata,'$.session_id') IS NOT NULL;
