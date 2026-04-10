# Jarvis — Personal Engineering Assistant

## Context

You lose context between Claude sessions, your work is spread across GitHub/Jira/Calendar/Kafka/docs/multiple repos, and there's no single place that understands your full workday. Jarvis solves this by being a local-first Python assistant that ingests activity from all your tools, builds a personal knowledge graph, and uses Claude to generate summaries, answer questions, and automate workflows.

## Architecture

- **Python** with `uv` for dependency management
- **SQLite** at `~/.jarvis/jarvis.db` — single file, FTS5 for search, JSON1 for metadata
- **Typer** CLI (`jarvis standup`, `jarvis log`, `jarvis search`, etc.)
- **FastAPI + HTMX + Jinja2** local web dashboard (no JS framework, no build step)
- **Claude API** for summarization, natural language queries, and correlation
- **httpx** for all API integrations
- **keyring** for secure credential storage (macOS Keychain)
- Config at `~/.jarvis/config.toml`

## Project Structure

```
jarvis/
├── pyproject.toml
├── docs/
│   └── SPEC.md
├── jarvis/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Typer app
│   ├── config.py            # pydantic-settings, reads ~/.jarvis/config.toml
│   ├── db.py                # SQLite init, schema, helpers
│   ├── models.py            # dataclass models
│   ├── brain.py             # Claude API orchestration
│   ├── memory.py            # Session memory capture/replay
│   ├── correlator.py        # Cross-source linking
│   ├── ingest.py            # Run all integrations
│   ├── integrations/
│   │   ├── base.py          # Integration protocol + RawEvent dataclass
│   │   ├── github.py
│   │   ├── jira.py
│   │   ├── gcal.py
│   │   ├── kafka.py
│   │   ├── git_local.py
│   │   └── docs.py
│   ├── workflows/
│   │   ├── standup.py
│   │   ├── meeting_prep.py
│   │   └── weekly_summary.py
│   └── web/
│       ├── app.py           # FastAPI
│       ├── routes.py
│       └── templates/
│           ├── base.html
│           ├── timeline.html
│           └── summary.html
├── migrations/
│   └── 001_initial.sql
└── tests/
    ├── test_cli.py
    ├── test_db.py
    └── test_integrations/
```

## Data Model (SQLite)

### events
Unified activity log from all sources.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | ULID (time-sortable) |
| source | TEXT | 'github', 'jira', 'gcal', 'kafka', 'git_local', 'docs' |
| kind | TEXT | 'pr_opened', 'commit', 'review', 'ticket_moved', 'meeting', etc. |
| title | TEXT | Event title |
| body | TEXT | Full description/content |
| metadata | TEXT | JSON blob for source-specific fields |
| url | TEXT | Link back to original source |
| happened_at | TEXT | ISO8601 timestamp |
| ingested_at | TEXT | Auto-set on insert |
| project | TEXT | Normalized project/repo name |

Dedup: `UNIQUE(source, kind, url)`. FTS5 index on title+body.

### entities
Named entities: people, repos, tickets, topics, docs.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | ULID |
| kind | TEXT | 'person', 'repo', 'ticket', 'topic', 'doc' |
| name | TEXT | Primary name |
| aliases | TEXT | JSON array of alternative names/handles |
| metadata | TEXT | JSON blob |

### event_entities
Links events to entities (the knowledge graph edges).

| Column | Type | Description |
|--------|------|-------------|
| event_id | TEXT FK | References events(id) |
| entity_id | TEXT FK | References entities(id) |
| role | TEXT | 'author', 'reviewer', 'assignee', 'mentioned', 'relates_to' |

### entity_links
Direct entity-to-entity relationships.

| Column | Type | Description |
|--------|------|-------------|
| from_id | TEXT FK | References entities(id) |
| to_id | TEXT FK | References entities(id) |
| relation | TEXT | 'works_on', 'owns', 'blocks', 'parent_of' |
| metadata | TEXT | JSON blob |

### sessions
Claude Code session memory snapshots.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | ULID |
| project | TEXT | Project/repo name |
| started_at | TEXT | ISO8601 |
| ended_at | TEXT | ISO8601 |
| context | TEXT | Markdown summary of what happened |
| raw_events | TEXT | JSON array of event IDs |

### summaries
Cached Claude-generated summaries.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | ULID |
| kind | TEXT | 'daily', 'weekly', 'standup', 'meeting_prep' |
| scope | TEXT | Project name or 'all' |
| period_start | TEXT | ISO8601 |
| period_end | TEXT | ISO8601 |
| content | TEXT | Generated markdown |
| event_ids | TEXT | JSON array of source event IDs |
| created_at | TEXT | Auto-set |
| model | TEXT | Which Claude model was used |

## Implementation Phases

### Phase 1: Foundation
1. **Scaffolding** — `pyproject.toml` with uv, package structure, `jarvis` CLI entry point
2. **Config** — `config.py` with pydantic-settings, `jarvis init` to create `~/.jarvis/`
3. **Database** — `db.py` with schema creation, `upsert_event`, `query_events`, `search_events`
4. **Integration protocol** — `base.py` with `Integration` protocol and `RawEvent` dataclass
5. **Git Local integration** — scan local repos via `git log`, zero API keys needed
6. **GitHub integration** — PRs, commits, reviews via REST API + httpx
7. **CLI commands** — `jarvis ingest`, `jarvis log`, `jarvis search`

### Phase 2: Intelligence
8. **brain.py** — Claude API wrapper (summarize_events, answer_query)
9. **`jarvis standup`** — query last 24h events, summarize with Claude
10. **`jarvis weekly`** — same for the week
11. **Jira integration** — poll for assigned issues, track status transitions
12. **Google Calendar integration** — fetch meetings, extract attendees
13. **Correlator** — link PRs to Jira tickets via branch name/title parsing, time-window matching

### Phase 3: Session Memory
14. **`jarvis context`** — generate a context briefing from recent sessions + events
15. **Session capture** — `jarvis session save` to record what was done
16. **Claude Code hook** — auto-inject context on session start
17. **`jarvis remember <note>`** — manual context capture
18. **`jarvis prep <meeting>`** — pull calendar event + related tickets/PRs/people

### Phase 4: Dashboard
19. **FastAPI app** — `jarvis web` starts local server
20. **Timeline view** — reverse-chronological event list with HTMX infinite scroll
21. **Daily/weekly summary pages** — Claude-generated, cached
22. **Search page** — FTS5 with HTMX live results
23. **Project view** — filtered activity per project

### Phase 5: Knowledge Graph (ongoing)
24. Kafka integration (parse shell history for hfkcat/kafka commands)
25. Entity resolution across sources (same person in GitHub/Jira/Calendar)
26. Pattern detection (time-of-day habits, collaboration frequency, context-switching)
27. Proactive suggestions
28. Automatic ingestion via launchd (every 15 min)

## Key Dependencies

```toml
dependencies = [
    "typer[all]>=0.9",
    "httpx>=0.27",
    "anthropic>=0.40",
    "pydantic-settings>=2",
    "python-ulid>=2",
    "keyring>=25",
    "tomli>=2",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "jinja2>=3.1",
]
```

No ORM — raw `sqlite3` with dataclass models. No heavy frameworks.

## Security

- Credentials in macOS Keychain via `keyring` — never in config files
- `~/.jarvis/config.toml` stores only non-secret config (usernames, URLs, repo lists)
- All data stays local — only outbound API calls to GitHub/Jira/Calendar/Claude
- `.gitignore` excludes `.env`, credentials, db files

## Verification

After Phase 1:
- `jarvis init` creates `~/.jarvis/` with config template and empty DB
- `jarvis ingest` pulls git commits and GitHub PRs into SQLite
- `jarvis log` displays recent events in a rich table
- `jarvis search "kafka"` returns FTS results
- `pytest tests/`

After Phase 2:
- `jarvis standup` outputs a Claude-generated standup from real activity data
- `jarvis standup --project <name>` scopes to one project
