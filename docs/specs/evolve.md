---
name: evolve
description: Re-ranks the feature backlog using activity signals from the DB and an LLM call, with caching and PR scaffolding
component: jarvis/evolve.py
---

# Spec — evolve

**Component:** `jarvis/evolve.py`

The evolve module reads `docs/TODO.md` and collects activity signals from the local database, then calls the LLM to produce a ranked list of features. Results are cached for 24 hours. A `--create-pr` flag scaffolds a spec file and opens a GitHub PR for a named feature.

## Behaviours

### F1. jarvis evolve reads TODO.md and activity signals, calls LLM, and prints a ranked list

**WHEN** the user runs `jarvis evolve` **THEN** the component **SHALL** read the raw content of `docs/TODO.md`, collect activity signals from the database, call the LLM with both, and print a numbered ranked list of features.

### F2. Signals include command frequency, top URL domains, and source distribution

**WHEN** activity signals are collected **THEN** the component **SHALL** include the top 5 CLI commands by frequency, the top 5 URL domains from browser history, and the event count per source for the last 30 days.

### F3. Output is a numbered list with feature name, phase, and rationale

**WHEN** the ranked list is printed **THEN** each line **SHALL** show the rank number, feature name, current phase, and a one-line rationale for its position.

### F4. LLM prompt includes TODO.md content and signals, requests JSON response

**WHEN** the LLM is called **THEN** the prompt **SHALL** include the raw TODO.md text and the collected signals, and ask for a JSON array of objects with fields `feature`, `phase`, `rationale`, and `score`.

### F5. Result is cached in the kv store with a 24-hour TTL

**WHEN** the LLM returns a valid response **THEN** the component **SHALL** store the result as JSON in the kv store under key `evolve_last_run` with a timestamp, and on subsequent calls within 24 hours return the cached result without calling the LLM.

### F6. --fresh bypasses the cache

**WHEN** the user runs `jarvis evolve --fresh` **THEN** the component **SHALL** ignore any cached result and call the LLM, then update the cache.

### F7. --create-pr scaffolds a spec file and opens a GitHub PR

**WHEN** the user runs `jarvis evolve --create-pr <feature-name>` **THEN** the component **SHALL** write a stub spec file at `docs/specs/<slug>.md`, commit it on a new branch, and invoke `gh pr create` to open a pull request containing only that spec file.

### F8. No activity data produces a helpful message and no LLM call

**WHEN** the database contains no events and no activity log entries **THEN** the component **SHALL** print a helpful message explaining that no activity data exists yet and exit without calling the LLM.
