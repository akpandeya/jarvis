---
name: memory
description: Session memory — captures work context as session snapshots and generates briefings for continuity across Claude sessions
component: jarvis/memory.py
---

# Memory

## Behaviours

**F1** WHEN `capture_session` is called and there are recent events THEN it SHALL call Claude to summarise them into 3–5 concise bullet points and save the result as a session record.

**F2** WHEN `capture_session` is called and there are no recent events THEN it SHALL save a "no recent activity" note without calling Claude.

**F3** WHEN `capture_session` is called with a project filter THEN it SHALL only include events for that project.

**F4** WHEN `generate_context` is called THEN it SHALL include both recent session snapshots and recent events in the prompt sent to Claude.

**F5** WHEN `generate_context` is called THEN the returned briefing SHALL contain recent work, open items, and suggested next steps, in under 200 words.

**F6** WHEN `generate_context` is called and there are no sessions or events THEN it SHALL return a "no recent activity" message without calling Claude.

**F7** WHEN `remember_note` is called THEN it SHALL save the note text directly as a session record without calling Claude.
