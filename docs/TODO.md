# Jarvis TODO

Prioritised feature backlog. Re-ranked by `jarvis evolve` based on actual usage. See `docs/VISION.md` for the full picture.

---

## Now — Phase 6 (Proactive Suggestions Engine)

- [ ] **SDD: Write `docs/specs/activity_tracker.md`** — behaviours for Firefox, Thunderbird, shell, CLI collectors
- [ ] **SDD: Write `docs/specs/suggestions_engine.md`** — behaviours for rule engine and suggestion store
- [ ] **Migration `002_phase6.sql`** — `activity_log` + `suggestions` tables
- [ ] **`jarvis/activity.py`** — activity tracker with 4 collectors (CLI, Firefox, Thunderbird, shell)
- [ ] **`jarvis/suggestions.py`** — rule engine (5 rules) + suggestion store CRUD
- [ ] **`jarvis/cli.py`** — `@track_usage` decorator, post-command suggestion banner, `jarvis suggest` command
- [ ] **`jarvis/brain.py`** — LLM response caching with TTL (standup=6h, weekly=24h, context=1h, prep=1h)
- [ ] **`jarvis/web/app.py`** — `/api/suggestions` endpoint + dashboard widget (HTMX poll 60s)
- [ ] **`.claude/commands/jarvis-suggest.md`** — Claude Code skill for in-session suggestions

---

## Next — Phase 7 (Self-Evolution Tracker)

- [ ] **`docs/ROADMAP.md`** — ranked feature backlog table with priority scores
- [ ] **`jarvis evolve`** — re-ranks roadmap using `command_frequency()` and `top_urls()` data
- [ ] **`jarvis evolve --create-pr <feature-id>`** — scaffolds spec + opens GitHub PR
- [ ] **`jarvis update`** — `git pull && uv sync` auto-update command
- [ ] **SDD: Write `docs/specs/evolve.md`**

---

## Next (continued) — PR Monitor

Scheduled every 2h via launchd. Polls all open PRs across all configured GitHub accounts.

- [ ] **SDD: Write `docs/specs/pr_monitor.md`** — behaviours for CI failure alert, review comment summary, auto-merge, staging→production prompt
- [ ] **`jarvis/pr_monitor.py`** — deterministic rules engine over GitHub PR state
  - CI failure → surface failing check name + link (no LLM)
  - New review comments since last check → LLM summarises them concisely (cached per PR+comment hash)
  - Approved + all checks green → auto-merge OR prompt if branch protection blocks
  - Deployed to staging → one-shot prompt to promote to production
- [ ] **Multi-account support** — iterate over all `gh` authenticated profiles; honour per-account token
- [ ] **`jarvis pr-status`** — on-demand CLI view of all open PRs with their state
- [ ] **Wire into launchd scheduler** — `jarvis pr-monitor --run` called every 2h alongside ingest

---

## Later — Phase 8+

- [ ] **Android integration** — FastAPI `/api/v1/` with bearer token auth; Tasker/Termux on Android
- [ ] **Local embeddings** — `sqlite-vec` + sentence-transformers for semantic search (no LLM)
- [ ] **Kafka activity tracking** — read actual topic offsets, not just shell history
- [ ] **Slack integration** — ingest DMs + channel mentions as events
- [ ] **Fully autonomous evolution** — Jarvis writes, tests, and PRs its own code changes

---

## Done

- [x] Phase 1: Core scaffold, SQLite DB, CLI, config
- [x] Phase 2: GitHub, Jira, GCal integrations; standup + weekly workflows
- [x] Phase 3: Session memory, context generation
- [x] Phase 4: FastAPI + HTMX web dashboard
- [x] Phase 5: Entity resolution, pattern detection, Kafka integration, launchd scheduling
- [x] SDD Constitution (`docs/specs/CONSTITUTION.md`)
- [x] Vision document (`docs/VISION.md`)
