# Jarvis — Vision

Jarvis is a personal assistant that knows what you're doing before you ask it anything.

It watches your computer — git commits, Jira tickets, calendar events, emails, browser history, shell commands — unifies all of it into a local timeline, and uses that context to surface the right action at the right moment. You don't interrogate it; it tells you what matters.

## Principles

**Local-first.** All data lives in SQLite at `~/.jarvis/jarvis.db`. Nothing leaves your machine unless you explicitly deploy it. Privacy by default.

**Deterministic-first.** Rules and structured pipelines run on every event, instantly and for free. The LLM is an escalation layer, not the default path. If a rule can answer the question, the LLM is never called.

**Proactive, not reactive.** Jarvis watches for signals — a meeting starting soon, a stale ingest, a day without a standup — and surfaces suggestions without being asked. You can ignore them or act on them in one command.

**Self-evolving.** Jarvis tracks its own usage patterns, re-ranks its feature backlog based on what you actually do, and can scaffold new features as specs + PRs for your review. Once merged, it updates itself.

**Installable.** Jarvis is a proper Python package (`uv tool install`). The CLI is the interface; the web dashboard and REST API are optional layers on top.

---

## What Jarvis Knows

| Source | What it ingests | How |
|---|---|---|
| Git (local) | Commits across all your repos | `git log` |
| GitHub | PRs, reviews, CI status — across all configured accounts | REST API (per profile token) |
| Jira | Ticket updates, status changes | `jira` CLI |
| Google Calendar | Events, attendees | Calendar API |
| Shell history | Commands run (`~/.zsh_history`) | File read |
| Firefox | Pages visited, search queries | `places.sqlite` |
| Thunderbird | Email subjects + senders | `global-messages-db.sqlite` / mbox |
| Jarvis CLI | Which commands you run, how often | Internal decorator |

---

## Three Horizons

### Now — Proactive Suggestions Engine
Jarvis watches your activity and fires deterministic rules. Results surface as a banner after CLI commands and as a widget on the web dashboard.

Rules (no LLM):
- Weekday morning with no standup generated → `jarvis standup`
- Last ingest > 2h ago → `jarvis ingest`
- Meeting in < 30min with attendees → `jarvis prep`
- Last session save > 4h, many events since → `jarvis session save`
- 3+ project switches in 2h → `jarvis context`
- PR with CI failure → LLM reads the failing log, explains what broke, and proposes a fix as a new commit on the PR branch
- PR with new review comments → LLM summarises the comments concisely
- PR approved and all checks green → auto-merges (or prompts if branch protection blocks it)
- PR deployed to staging → asks whether to promote to production, once per PR, across all configured GitHub profiles

LLM is called only when a rule needs prose generation (e.g., meeting prep brief, review comment summary), and the result is cached.

### Next — Self-Evolution Tracker
Jarvis scores its own feature backlog against your usage data (`command_frequency`, `top_urls`, `recent_emails`). It re-ranks what to build next and can scaffold a new feature as a spec + PR for your review.

`jarvis evolve` — shows re-ranked roadmap  
`jarvis evolve --create-pr <feature-id>` — opens a PR with the spec

Auto-update: once a PR merges, `jarvis update` pulls and reinstalls.

### Later — Ambient Awareness
- **Android integration**: Jarvis REST API on localhost, queried via Tasker/Termux from your phone
- **Local embeddings**: `sqlite-vec` + sentence-transformers for semantic search without LLM calls
- **Fully autonomous evolution**: Jarvis writes, tests, and proposes its own code changes based on usage signals
- **PR monitor** (scheduled every 2h via launchd): polls all open PRs across all configured GitHub accounts; fires deterministic rules for CI failures and staging deploys; calls LLM only for review comment summaries

---

## Claude Skill

A `/jarvis-suggest` skill for Claude Code sessions surfaces Jarvis context inside any coding session:

1. Runs `jarvis suggest` → pending suggestions
2. Runs `jarvis context --raw` → recent activity
3. Synthesises a "what to do next" brief
4. Offers to act on the top suggestion

---

## Non-Goals

- Not a general-purpose chatbot. It knows about *your work*, not everything.
- Not a cloud service. No SaaS, no accounts. Local SQLite is the database.
- Not a replacement for your existing tools. It reads from them; it doesn't replace them.
