---
name: db
description: SQLite database layer — schema migrations, event/entity/activity/suggestion CRUD, and FTS5 search
component: jarvis/db.py
---

# Database

## Behaviours

**F1** WHEN `init_db` is called THEN it SHALL execute every `*.sql` file in the `migrations/` directory in ascending filename order.

**F2** WHEN `get_db` is called and the database file does not exist THEN it SHALL initialise the schema before returning the connection.

**F3** WHEN `upsert_event` is called with a duplicate event THEN it SHALL silently ignore the duplicate and return the existing ID.

**F4** WHEN `insert_activity` inserts a new row THEN it SHALL return `True`; WHEN the row already exists it SHALL return `False`.

**F5** WHEN `query_events` is called with a `days` value THEN it SHALL only return events whose `happened_at` is within that many days of now.

**F6** WHEN `search_events` is called THEN it SHALL use the FTS5 virtual table ordered by relevance rank.

**F7** WHEN `upsert_entity` is called with a name that already exists for that kind THEN it SHALL return the existing entity ID without inserting a duplicate.

**F8** WHEN `upsert_suggestion` is called with a `rule_id` that already has a row THEN it SHALL update the message, action, and priority in place.

**F9** WHEN `get_pending_suggestions` is called THEN it SHALL exclude dismissed rows and rows whose `snoozed_until` is in the future.

**F10** WHEN any write operation completes THEN the connection SHALL commit before returning.

**F11** WHEN a connection is opened THEN WAL journal mode and foreign key enforcement SHALL be enabled.
