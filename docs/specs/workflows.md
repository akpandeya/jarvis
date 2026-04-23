---
name: workflows
description: AI-generated work summaries — standup notes and weekly summary, both built on brain.py
component: jarvis/workflows/
---

# Workflows

## Standup

**F1** WHEN `generate_standup` is called and no events are found THEN it SHALL return a no-activity message without calling Claude.

**F2** WHEN `generate_standup` is called with `days=1` THEN the summary SHALL use "Yesterday" as the period heading.

**F3** WHEN `generate_standup` is called with `days > 1` THEN the summary SHALL use a "Last N days" period heading and group output by day.

**F4** WHEN `generate_standup` is called with a project or source filter THEN only events matching that filter SHALL be included.

**F5** WHEN `generate_standup` produces output THEN it SHALL include three sections: yesterday/period, today (inferred next steps), and blockers.

---

## Weekly Summary

**F6** WHEN `generate_weekly` is called and no events are found THEN it SHALL return a no-activity message without calling Claude.

**F7** WHEN `generate_weekly` is called THEN it SHALL query the last 7 days of events.

**F8** WHEN `generate_weekly` produces output THEN it SHALL include three sections: key accomplishments, in-progress items, and themes.

**F9** WHEN `generate_weekly` is called with a project or source filter THEN only events matching that filter SHALL be included.
