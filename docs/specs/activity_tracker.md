---
name: activity_tracker
description: Collects computer-wide activity (CLI, Firefox, Thunderbird, shell) and writes it to the activity_log table
component: jarvis/activity.py
---

# Spec — ActivityTracker

**Component:** `jarvis/activity.py`

`ActivityTracker` collects activity events from four sources and upserts them into the `activity_log` table. Each source is an independent collector that can be run individually or together via `collect_all`.

## Glossary

- **activity event** — a single observable computer action: a CLI command run, a page visited, an email received, or a shell command executed.
- **happened_at** — ISO 8601 UTC timestamp of when the activity occurred, derived from the source data (not ingestion time).

## Behaviours

### F1. collect_all runs all four collectors and returns the total count of new rows inserted

**WHEN** `collect_all(since)` is called **THEN** `ActivityTracker` **SHALL** invoke each collector (`cli`, `firefox`, `thunderbird`, `shell`) in sequence and return the sum of new rows inserted across all collectors.

### F2. Each collector skips sources that are unavailable without raising

**WHEN** a collector's source is unavailable (Firefox not installed, history file absent, DB locked and unreadable) **THEN** that collector **SHALL** return `0` and log a warning, leaving other collectors unaffected.

### F3. CLI tracker records command name, args, project, duration, and exit code

**WHEN** a Jarvis CLI command completes **THEN** `ActivityTracker.record_cli` **SHALL** insert one row into `activity_log` with `source="jarvis_cli"`, `kind="command"`, `title` equal to the command name, `body` equal to the JSON-serialised argv, and `metadata` containing `exit_code` and `duration_ms`.

### F4. Firefox collector reads from all profile places.sqlite files

**WHEN** `collect_firefox(since)` is called **THEN** the collector **SHALL** query `moz_places JOIN moz_historyvisits` from every `places.sqlite` found under `~/Library/Application Support/Firefox/Profiles/*/` and insert rows with `source="firefox"`, `kind="page_visit"`, `title` from `moz_places.title`, `url` from `moz_places.url`, and `happened_at` derived from `moz_historyvisits.visit_date` (microseconds since epoch).

### F5. Firefox collector copies a locked database before reading

**WHEN** a `places.sqlite` file cannot be opened directly (Firefox is running and holds a write lock) **THEN** the collector **SHALL** copy the file to a temp path and query the copy, then delete the temp file after reading.

### F6. Thunderbird collector reads email subjects and senders only

**WHEN** `collect_thunderbird(since)` is called **THEN** the collector **SHALL** insert rows with `source="thunderbird"`, `kind="email"`, `title` equal to the message subject, `body` equal to the sender address, and `happened_at` derived from the message date. It **SHALL NOT** store message body text.

### F7. Shell collector reads ~/.zsh_history and filters noise

**WHEN** `collect_shell(since)` is called **THEN** the collector **SHALL** parse `~/.zsh_history` extended format (`: <timestamp>:<elapsed>;<command>`), insert rows with `source="shell"`, `kind="shell_cmd"`, `title` equal to the command string, and `happened_at` derived from the timestamp field. Commands whose first token is in `{"ls", "cd", "clear", "pwd", "exit", "history"}` **SHALL** be skipped.

### F8. All collectors deduplicate by (source, kind, url, happened_at)

**WHEN** a collector attempts to insert a row that already exists in `activity_log` with the same `source`, `kind`, `url`, and `happened_at` **THEN** the row **SHALL** be silently skipped (upsert with `OR IGNORE`).

### F9. collect_all logs a summary line per collector

**WHEN** `collect_all` completes **THEN** `ActivityTracker` **SHALL** emit one log line per collector in the form `"<source>: <n> new rows"`.
