# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Context

At the start of each conversation, run `jarvis context --raw` to get a briefing of recent work.
At the end of a session (before the user leaves), run `jarvis session save` to capture what was done.

## Commands

```bash
uv run pytest                        # run all tests
uv run pytest tests/test_foo.py      # run a single test file
uv run pytest -m spec                # run only spec-tagged behaviour tests
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv pip install -e .                  # install jarvis CLI in editable mode
jarvis web                           # start FastAPI dashboard (localhost:8000)
```

## Architecture

Jarvis ingests activity from multiple sources into a local SQLite database (`~/.jarvis/jarvis.db`), then uses Claude (via subprocess to `claude -p --bare`) to generate summaries on demand. No API key is managed in this repo — it piggybacks on Claude Code's auth.

**Data flow:**
```
integrations/* → ingest.py → db.py (SQLite) → workflows/* / brain.py → CLI output / web dashboard
```

**Key modules:**
- `jarvis/ingest.py` — orchestrates all integrations; runs `correlator.py` and `resolver.py` post-ingest
- `jarvis/brain.py` — all Claude calls; formats events as markdown bullets, shells out to `claude -p --bare`
- `jarvis/db.py` — raw sqlite3 (no ORM); FTS5 virtual table on events; ULID primary keys
- `jarvis/config.py` — pydantic-settings reading `~/.jarvis/config.toml`; credentials go to macOS Keychain via `keyring`
- `jarvis/integrations/base.py` — `Integration` protocol every source must implement (`fetch_since`, `health_check`)
- `jarvis/web/app.py` — FastAPI + HTMX + Jinja2; no JS framework, no build step

**Entity graph:** Events link to Entities (person/repo/ticket/topic) via `event_entities`. `correlator.py` extracts Jira-style ticket IDs from event text; `resolver.py` deduplicates people via Union-Find on name/email prefix matching.

## Spec-Driven Development (SDD)

All new modules must have a spec in `docs/specs/` before code is written. Read `docs/specs/CONSTITUTION.md` first.

- Format: YAML frontmatter (`name`/`description`/`component`) + flat `F<n>` behaviour list in EARS style (`WHEN … THEN … SHALL …`)
- Spec is source of truth — if code and spec disagree, the code is the bug
- Write behaviours in plain English — no function signatures, parameter names, or code syntax in behaviour text. The tagged test carries the implementation detail.
- Tag tests: `@pytest.mark.spec("module_name.F<n>")`
- New post-bootstrap behaviours carry a GitHub issue ref `(#<n>)`
- Spec discovery: `grep -l "^component:" docs/specs/*.md`

Feature backlog and roadmap: `docs/TODO.md` and `docs/VISION.md`.

## Jarvis CLI commands (for reference)

- `jarvis ingest [--source]` — pull events
- `jarvis standup [--days N]` — AI standup summary
- `jarvis context [--raw]` — session context briefing
- `jarvis session save` — capture session snapshot
- `jarvis remember "note"` — manual note
- `jarvis suggest` — show proactive suggestions (Phase 6)
- `jarvis evolve` — re-rank feature backlog (Phase 7)
