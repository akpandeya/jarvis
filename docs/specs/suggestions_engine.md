---
name: suggestions_engine
description: Evaluates deterministic rules against activity data and maintains a store of actionable suggestions
component: jarvis/suggestions.py
---

# Spec — SuggestionsEngine

**Component:** `jarvis/suggestions.py`

`SuggestionsEngine` runs a set of deterministic rules against the local database and surfaces actionable suggestions without calling an LLM. Each rule produces at most one suggestion; suggestions are stored in the `suggestions` table and queried cheaply after every CLI command.

## Glossary

- **pending suggestion** — a suggestion that is not dismissed and whose `snoozed_until` is either null or in the past.
- **rule** — an object with a `rule_id: str` and an `evaluate(db) -> Suggestion | None` method.

## Behaviours

### F1. evaluate_all runs every registered rule and upserts results

**WHEN** `evaluate_all(db)` is called **THEN** `SuggestionsEngine` **SHALL** call `evaluate(db)` on each registered rule, and for each non-`None` result upsert a row into the `suggestions` table keyed on `rule_id`, overwriting `message` and `action` if the rule fires again.

### F2. evaluate_all does not upsert when a rule returns None

**WHEN** a rule's `evaluate(db)` returns `None` **THEN** `evaluate_all` **SHALL NOT** insert or update any row for that `rule_id`.

### F3. get_pending returns only active suggestions ordered by priority

**WHEN** `get_pending(db)` is called **THEN** it **SHALL** return all suggestions where `dismissed = 0` and (`snoozed_until` is null OR `snoozed_until < now()`), ordered by `priority DESC`.

### F4. no_standup rule fires on weekdays between 09:00 and 11:00 when no standup exists today

**WHEN** `evaluate(db)` is called on the `no_standup` rule, the current day is Monday–Friday, the local time is between 09:00 and 11:00, and no row exists in `summaries` with `kind="standup"` and `created_at` on today's date **THEN** the rule **SHALL** return a suggestion with `action="jarvis standup"` and `priority=80`.

### F5. stale_ingest rule fires when the last ingest was more than 2 hours ago

**WHEN** `evaluate(db)` is called on the `stale_ingest` rule and the most recent `happened_at` in the `events` table is more than 2 hours before now **THEN** the rule **SHALL** return a suggestion with `action="jarvis ingest"` and `priority=70`.

### F6. meeting_soon rule fires when a calendar event starts within 30 minutes and has more than one attendee

**WHEN** `evaluate(db)` is called on the `meeting_soon` rule and an event exists in the `events` table with `source="gcal"`, `happened_at` between now and now+30 minutes, and `metadata` containing more than one attendee **THEN** the rule **SHALL** return a suggestion with `action='jarvis prep "<event title>"'` and `priority=90`.

### F7. unsaved_session rule fires when session save is overdue

**WHEN** `evaluate(db)` is called on the `unsaved_session` rule, the most recent `sessions` row is more than 4 hours old, and more than 10 events have been inserted since that session **THEN** the rule **SHALL** return a suggestion with `action="jarvis session save"` and `priority=60`.

### F8. context_drift rule fires on 3 or more project switches within 2 hours

**WHEN** `evaluate(db)` is called on the `context_drift` rule and the `events` table contains 3 or more distinct `project` values among events with `happened_at` in the last 2 hours **THEN** the rule **SHALL** return a suggestion with `action="jarvis context"` and `priority=50`.

### F9. dismiss marks a suggestion so it no longer appears in get_pending

**WHEN** `dismiss(db, suggestion_id)` is called **THEN** the suggestion row **SHALL** have `dismissed = 1` and **SHALL NOT** appear in subsequent `get_pending` results.

### F10. snooze suppresses a suggestion until the given datetime

**WHEN** `snooze(db, suggestion_id, until)` is called **THEN** the suggestion row **SHALL** have `snoozed_until` set to `until` and **SHALL NOT** appear in `get_pending` results before that time.
