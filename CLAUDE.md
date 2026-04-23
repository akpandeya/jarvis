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

## Branch Naming & Versioning

**Always create a feature branch — never commit directly to `main`.** Branch protection requires a PR and passing CI before merge.

Branch names control the automatic version bump on merge:

| Prefix | When to use | Version bump | Example |
|---|---|---|---|
| `feat/` | New user-visible capability | minor (`0.2.0` → `0.3.0`) | `feat/ingest-ux` |
| `fix/` | Bug fix, regression, crash | patch (`0.2.0` → `0.2.1`) | `fix/update-repo-path` |
| `patch/` | Non-bug small change (copy, style) | patch | `patch/badge-wording` |
| `major/` or `breaking/` | Breaking API or behaviour change | major (`0.2.0` → `1.0.0`) | `major/new-config-format` |

Anything else (e.g. `chore/`, `docs/`) defaults to patch.

The bump runs automatically via GitHub Actions after every merge to `main`, updating `pyproject.toml` and `jarvis/__init__.py`. Dev builds show `0.3.0-dev+abc1234`; the installed tool shows clean `0.3.0`.

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
