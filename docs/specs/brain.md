---
name: brain
description: Claude integration — formats events as context and calls the claude CLI for summaries and queries
component: jarvis/brain.py
---

# Brain

## Behaviours

**F1** WHEN `summarize_events` is called THEN it SHALL call the `claude` CLI in print mode using the configured system prompt for the requested type.

**F2** WHEN the `claude` CLI is not installed THEN brain SHALL raise a runtime error before attempting any call.

**F3** WHEN the `claude` CLI exits with a non-zero return code THEN brain SHALL raise a runtime error containing the stderr output.

**F4** WHEN events are formatted and the list is empty THEN brain SHALL return a "no events found" placeholder string rather than an empty string.

**F5** WHEN an event has a URL THEN the formatted output SHALL include it in parentheses after the title.

**F6** WHEN an event body is shorter than 500 characters THEN the formatted output SHALL include up to 300 characters of it, indented under the event line.

**F7** WHEN an event has a `sha` in metadata THEN the formatted output SHALL include the first 8 characters as `sha:<short>`.

**F8** WHEN an event has a `number` in metadata THEN the formatted output SHALL include it as `#<number>`.

**F9** WHEN `summarize_events` is called with `prompt_type="standup"` and `days=1` THEN the system prompt SHALL refer to "Yesterday".

**F10** WHEN `summarize_events` is called with `prompt_type="standup"` and `days > 1` THEN the system prompt SHALL refer to "Last N days".

**F11** WHEN `answer_query` is called THEN the user message sent to Claude SHALL contain both the formatted events and the user's question.
