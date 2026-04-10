# Jarvis

Personal engineering assistant. Python, uv, SQLite.

## Session Context

At the start of each conversation, run `jarvis context --raw` to get a briefing of recent work.
At the end of a session (before the user leaves), run `jarvis session save` to capture what was done.

## Commands

- `jarvis ingest` — pull events from git/jira
- `jarvis standup --days N` — generate standup
- `jarvis log` — show recent events
- `jarvis search "query"` — full-text search
- `jarvis context` — session context briefing
- `jarvis session save` — capture session
- `jarvis remember "note"` — save a note
- `jarvis prep "topic"` — meeting prep
- `jarvis ask "question"` — ask about work history

## Project structure

- `jarvis/cli.py` — Typer CLI commands
- `jarvis/brain.py` — Claude CLI integration (uses `claude -p --bare`)
- `jarvis/memory.py` — Session memory capture/replay
- `jarvis/db.py` — SQLite database layer
- `jarvis/integrations/` — Data source integrations (git_local, github, jira, gcal)
- `jarvis/workflows/` — Standup, weekly summary generators
- `jarvis/config.py` — Config from ~/.jarvis/config.toml
- `docs/SPEC.md` — Full project spec
