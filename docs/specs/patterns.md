---
name: patterns
description: Work pattern detection — analyses event data for time distribution, collaboration frequency, and context-switching rate
component: jarvis/patterns.py
---

# Patterns

## Behaviours

**F1** WHEN `time_of_day_distribution` is called THEN it SHALL return a count for each of the 24 hours of the day, including hours with zero events.

**F2** WHEN `day_of_week_distribution` is called THEN it SHALL return a count for each of the 7 days of the week, including days with zero events.

**F3** WHEN `context_switches` is called THEN it SHALL count the number of times consecutive events within a day belong to different projects, treating events with no project as belonging to their source.

**F4** WHEN `context_switches` is called THEN it SHALL return both a per-day breakdown and the average switches per day.

**F5** WHEN `collaboration_frequency` is called THEN it SHALL count events linked to person entities and return the top collaborators ordered by event count.

**F6** WHEN `source_distribution` is called THEN it SHALL return event counts grouped by source, ordered by count descending.

**F7** WHEN `project_distribution` is called THEN events with no project SHALL be counted under the label `(none)`.

**F8** WHEN `generate_insights` is called THEN it SHALL return a markdown string summarising peak hour, peak day, top sources, top projects, average context switches, and top collaborators.

**F9** WHEN `generate_insights` is called and there is no event data THEN it SHALL return a "not enough data" message rather than an empty string.
