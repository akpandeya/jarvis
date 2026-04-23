---
name: pr_monitor
description: Polls open PRs across all configured GitHub repos every 2h via launchd. Explains CI failures with LLM, summarises review comments, auto-merges approved+green PRs, and flags oversized PRs deterministically.
component: jarvis/pr_monitor.py
---

# PR Monitor

## Behaviours

**F1** WHEN the monitor runs THEN it SHALL poll all open PRs for every repo listed in `config.github.repos`.

**F2** WHEN a PR has a failing CI check THEN the monitor SHALL fetch the failing log text, call the LLM to explain the root cause, and post a comment on the PR with the explanation; the comment SHALL only be posted once per run_id (cached so the same failure never triggers a second comment).

**F3** WHEN a PR has new review comments since the last check THEN the monitor SHALL summarise them with the LLM and store the summary as a suggestion; the LLM call SHALL be cached per comment hash so the same comments are never re-summarised.

**F4** WHEN a PR is approved AND all CI checks are green THEN the monitor SHALL auto-merge the PR using squash merge.

**F5** WHEN a PR has more than the configured `max_files` changed files THEN the monitor SHALL surface a suggestion to split it; this check is deterministic and SHALL NOT call the LLM.

**F6** WHEN the monitor runs THEN it SHALL store the last-seen state in the kv store (`last_pr_check_at` and per-PR comment hashes keyed as `pr_comments_hash:{pr_number}`); CI explanation cache keys SHALL be `pr_ci_explained:{run_id}`.

**F7** WHEN the monitor is called multiple times THEN it SHALL be idempotent — a second run SHALL NOT re-post a CI comment or re-summarise comments that have already been processed.

**F8** WHEN the launchd agent is installed THEN it SHALL run the monitor every 7200 seconds (2 hours) via `com.jarvis.pr_monitor` with `RunAtLoad: false`.

**F9** WHEN the GitHub token is not configured in the keychain THEN the monitor SHALL log a warning and exit cleanly without error.

**F10** WHEN any LLM call is made THEN the result SHALL be cached — the same `run_id` or `comment_hash` SHALL never trigger a second LLM call.
