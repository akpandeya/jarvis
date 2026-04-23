---
name: suggestions_engine
description: Evaluates deterministic rules against activity data and maintains a store of actionable suggestions
component: jarvis/suggestions.py
---

# Spec — SuggestionsEngine

**Component:** `jarvis/suggestions.py`

SuggestionsEngine runs a set of deterministic rules against the local database and surfaces actionable suggestions without calling an LLM. Each rule produces at most one suggestion; suggestions are stored and queried cheaply after every CLI command.

## Glossary

- **pending suggestion** — a suggestion that is not dismissed and whose snooze time is either unset or in the past.
- **rule** — a component that inspects the database and returns either a suggestion or nothing.

## Behaviours

### F1. All rules are evaluated and results are stored

**WHEN** the engine is asked to evaluate **THEN** SuggestionsEngine **SHALL** run every registered rule and upsert the result into the suggestions store keyed by rule ID, overwriting the message and action if the rule fires again.

### F2. A rule that produces no result leaves the store unchanged

**WHEN** a rule finds no trigger condition **THEN** the engine **SHALL NOT** insert or update any row for that rule.

### F3. Pending suggestions are returned ordered by priority

**WHEN** pending suggestions are requested **THEN** the engine **SHALL** return all suggestions that are not dismissed and are not currently snoozed, ordered from highest to lowest priority.

### F4. no_standup rule fires on weekday mornings when no standup has been generated today

**WHEN** it is a weekday between 09:00 and 11:00 local time and no standup summary exists for today **THEN** the rule **SHALL** produce a suggestion to run `jarvis standup` with priority 80.

### F5. stale_ingest rule fires when ingestion has not run recently

**WHEN** the most recent ingested event is more than 2 hours old **THEN** the rule **SHALL** produce a suggestion to run `jarvis ingest` with priority 70.

### F6. meeting_soon rule fires when a meeting with attendees is starting shortly

**WHEN** a calendar event with more than one attendee is starting within the next 30 minutes **THEN** the rule **SHALL** produce a suggestion to prepare for that meeting with priority 90. This rule requires the calendar integration to have run recently enough to have populated upcoming events.

### F7. unsaved_session rule fires when the session has not been saved for a long time

**WHEN** the last session save was more than 4 hours ago and more than 10 events have occurred since **THEN** the rule **SHALL** produce a suggestion to run `jarvis session save` with priority 60.

### F8. context_drift rule fires on frequent project switching

**WHEN** 3 or more distinct projects appear in events from the last 2 hours **THEN** the rule **SHALL** produce a suggestion to run `jarvis context` with priority 50.

### F9. Dismissing a suggestion removes it from pending results

**WHEN** a suggestion is dismissed **THEN** it **SHALL NOT** appear in subsequent pending results.

### F10. Snoozing a suggestion hides it until the given time

**WHEN** a suggestion is snoozed until a given time **THEN** it **SHALL NOT** appear in pending results before that time.
