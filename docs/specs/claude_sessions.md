---
name: claude_sessions
description: Reads all Claude Code sessions from ~/.claude/projects/**/*.jsonl and surfaces each as an event, regardless of whether they were started via jarvis
component: jarvis/integrations/claude_sessions.py
---

# Claude Sessions Integration

## Behaviours

**F1** WHEN `fetch_since` is called THEN it SHALL scan all `*.jsonl` files under `~/.claude/projects/` recursively, skipping any file whose path contains a `subagents` directory.

**F2** WHEN a valid session file is parsed THEN it SHALL produce exactly one event with `source="claude_sessions"` and `kind="session"`, regardless of how many messages the session contains.

**F3** WHEN the first user message timestamp in a session is older than `since` THEN that session SHALL be skipped and no event produced.

**F4** WHEN an event is produced THEN its title SHALL be the project name in brackets followed by the first user message truncated to 100 characters.

**F5** WHEN an event is produced THEN its body SHALL be the first assistant text response truncated to 500 characters.

**F6** WHEN `health_check` is called THEN it SHALL return True if `~/.claude/projects/` exists and False otherwise.

**F7** WHEN a session file cannot be read or parsed THEN it SHALL be silently skipped without raising an exception.
