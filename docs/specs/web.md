---
name: web
description: FastAPI + HTMX web dashboard — timeline, search, insights, AI summaries, and suggestions widget
component: jarvis/web/app.py
---

# Web Dashboard

## Timeline

**F1** WHEN the timeline page is loaded THEN it SHALL show the most recent events filtered by the selected source, project, and days range.

**F2** WHEN a request includes the `HX-Request` header THEN the timeline endpoint SHALL return only the events partial template, not the full page.

**F3** WHEN `source` or `project` query params are provided THEN the event list SHALL be filtered to match.

---

## Search

**F4** WHEN `/search` is loaded with a non-empty query THEN it SHALL return events matching the FTS5 full-text search.

**F5** WHEN `/search` is loaded with an empty query THEN it SHALL return an empty results list without querying the database.

---

## AI Summary

**F6** WHEN `/api/summary` is called THEN it SHALL call Claude via `brain.py` and return the result as HTML.

**F7** WHEN `/api/summary` is called with no matching events THEN it SHALL return a "no events found" HTML response without calling Claude.

---

## Insights

**F8** WHEN `/insights` is loaded THEN it SHALL display time-of-day, day-of-week, source, project, collaborator, and context-switch data for the selected period.

---

## Suggestions Widget

**F9** WHEN `/api/suggestions` is called THEN it SHALL run `evaluate_all` and return all pending (non-dismissed, non-snoozed) suggestions as JSON.

**F10** WHEN the suggestions widget is loaded THEN it SHALL poll `/api/suggestions` every 60 seconds via HTMX and update in place.

---

## Sessions

**F11** WHEN `/sessions` is loaded THEN it SHALL list recent session snapshots, optionally filtered by project.

---

## Ingest Button

**F12** WHEN the "Run Ingest" button is clicked THEN it SHALL be disabled and show a loading indicator while ingest runs, display per-source log lines on completion, re-enable after the response, and trigger a page reload 1.5 seconds after settling.

**F13** WHEN the stale_ingest suggestion is displayed THEN its action SHALL be a clickable "Run Ingest" button rather than a static code block.
