---
name: pr_monitor
description: Polls open PRs across all configured GitHub accounts every 2h and surfaces actionable signals — CI failures, review comments, auto-merge readiness, staging deploys, and oversized diffs
component: jarvis/pr_monitor.py
---

# PR Monitor

## Behaviours

**F1** WHEN the monitor runs THEN it SHALL poll all open PRs for every GitHub account token stored in the macOS Keychain under the configured account keys.

**F2** WHEN a PR has a failing CI check that was not failing on the previous run THEN the monitor SHALL fetch the failing job log, call LLM to diagnose the root cause, and surface the explanation plus a proposed fix as a suggestion.

**F3** WHEN the LLM proposes a fix for a CI failure THEN the suggestion action SHALL be the `jarvis pr-fix` command with the PR number, so the user can review before anything is committed.

**F4** WHEN a PR has new review comments since the last check THEN the monitor SHALL call LLM to summarise them concisely and surface the summary as a suggestion; the LLM result SHALL be cached per PR number and comment hash so the same comments are never re-summarised.

**F5** WHEN a PR is approved by all required reviewers AND all required checks are green THEN the monitor SHALL surface a suggestion to merge it; if the repo allows auto-merge it SHALL offer to enable it.

**F6** WHEN a PR has more changed files or lines than the configured thresholds THEN the monitor SHALL call LLM to analyse the diff and suggest a concrete stacking or split plan as a suggestion.

**F7** WHEN a PR has been deployed to a staging environment (detected via a deployment event with environment name matching configured staging patterns) THEN the monitor SHALL surface a one-shot suggestion to promote it to production; this suggestion SHALL only fire once per PR.

**F8** WHEN any LLM call is made THEN the result SHALL be cached keyed on the relevant content hash (log hash for CI, comment hash for reviews, diff hash for size); a cached result SHALL be returned without calling LLM again for the same content.

**F9** WHEN the monitor completes a run THEN it SHALL record a `pr_monitor` row in `activity_log` with counts of PRs checked and signals fired.

**F10** WHEN `jarvis pr-status` is run THEN it SHALL display a table of all open PRs across all configured accounts with their CI status, review status, and any pending signals.

**F11** WHEN `jarvis pr-fix <pr-number>` is run THEN it SHALL show the LLM-proposed fix and prompt the user to confirm before pushing a commit to the PR branch.

**F12** WHEN the PR size thresholds are not configured THEN the defaults SHALL be 10 changed files or 500 changed lines.
