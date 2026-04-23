---
name: ingest
description: Orchestrates all integrations — fetches events, stores them, then runs correlation, entity resolution, and activity collection
component: jarvis/ingest.py
---

# Ingest

## Behaviours

**F1** WHEN an integration's source does not appear in the config (e.g. no repos listed, no credentials path) THEN ingest SHALL skip that integration without error.

**F2** WHEN an integration's `health_check` returns False THEN ingest SHALL skip it and print a yellow "skip" warning.

**F3** WHEN an integration is run THEN ingest SHALL store every returned event via `upsert_event` and link its entities.

**F4** WHEN all integrations have run THEN ingest SHALL run `correlate_events` and log the number of new links created.

**F5** WHEN all integrations have run THEN ingest SHALL run `resolve_entities` and log the number of merges performed.

**F6** WHEN `source_filter` is None or `"activity"` THEN ingest SHALL run `collect_all` for activity tracking after integrations complete.

**F7** WHEN `source_filter` is set to a specific source name THEN ingest SHALL only run integrations and collectors matching that name.

**F8** WHEN `ingest_all` completes THEN it SHALL return the total count of new events stored across all integrations.
