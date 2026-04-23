---
name: correlator
description: Cross-source correlation — extracts Jira-style ticket IDs from events and links them to ticket entities
component: jarvis/correlator.py
---

# Correlator

## Behaviours

**F1** WHEN an event's title or body contains a Jira-style ticket ID (e.g. `PROJ-123`) THEN `correlate_events` SHALL create or find a ticket entity for that ID and link the event to it with role `relates_to`.

**F2** WHEN the same ticket ID appears in multiple events THEN all those events SHALL be linked to the same ticket entity.

**F3** WHEN an event's title and body contain no ticket IDs THEN no entity link SHALL be created for that event.

**F4** WHEN `find_related_events` is called with an event ID THEN it SHALL return other events that share at least one entity with that event, ordered by recency.

**F5** WHEN `find_related_events` is called THEN the source event itself SHALL not appear in the results.

**F6** WHEN `correlate_events` completes THEN it SHALL return the total count of new event-entity links created.
