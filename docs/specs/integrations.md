---
name: integrations
description: Integration protocol and source-specific adapters — GitHub, Jira, GCal, git local, Kafka
component: jarvis/integrations/
---

# Integrations

## Protocol (base)

**F1** WHEN `health_check` returns False THEN ingest SHALL skip that integration and show a warning.

**F2** WHEN `fetch_since` is called THEN it SHALL return only events with `happened_at` after the given datetime.

**F3** WHEN an integration cannot connect (network error, missing credentials) THEN `health_check` SHALL return False without raising an exception.

---

## GitHub

**F4** WHEN the GitHub token is absent from the macOS Keychain THEN `health_check` SHALL return False.

**F5** WHEN a pull request is authored by the configured username THEN the event kind SHALL be `pr_opened`.

**F6** WHEN a pull request is authored by someone else THEN the event kind SHALL be `pr_review_requested`.

**F7** WHEN a pull request has requested reviewers THEN each reviewer SHALL be stored as a person entity linked to the event with role `reviewer`.

**F8** WHEN a commit is fetched THEN the author SHALL be stored as a person entity linked to the event with role `author`.

**F9** WHEN a PR's `updated_at` is before `since` THEN that PR and all older ones in the response SHALL be skipped.

---

## Jira

**F10** WHEN `jira` CLI is not installed or not authenticated THEN `health_check` SHALL return False.

**F11** WHEN project keys are configured THEN only issues belonging to those projects SHALL be fetched.

---

## Google Calendar

**F12** WHEN the credentials path is empty or the file does not exist THEN `health_check` SHALL return False.

**F13** WHEN a calendar event has attendees THEN each attendee SHALL be stored as a person entity linked to the event.

---

## Git (local)

**F14** WHEN a repo path does not exist on disk THEN that repo SHALL be skipped without error.

**F15** WHEN commits are fetched THEN the author name and email SHALL be stored as a person entity linked to the event with role `author`.

---

## Kafka

**F16** WHEN the Kafka integration is enabled THEN it SHALL parse `~/.zsh_history` for `hfkcat` and `kcat` commands and emit them as events.

**F17** WHEN a shell history line has no timestamp THEN it SHALL be skipped.
