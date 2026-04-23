# Spec Constitution

This document governs how specs are written in `docs/specs/`. Every spec and every spec-backed test must follow these rules.

## 1. Purpose

Specs describe the **observable behaviour** of a component. They are the source of truth for:

- What a reviewer checks the code against.
- What a test verifies.
- What a future engineer (or AI session) reads first to understand a component.

If the code and the spec disagree, the **spec wins**: the code is the bug. Fix the mismatch in the same PR that caused it — either correct the code or update the spec (with a GitHub issue ref on the changed behaviour).

## 2. Format

A spec is a flat, numbered list of behaviours. Each behaviour has:

- An ID of the form `F<n>` — stable for the life of the component.
- EARS-style wording: **WHEN** `<trigger>` **THEN** the component **SHALL** `<observable outcome>`.
- A trailing GitHub issue reference on any behaviour added *after* the spec was first created: `(#<n>)`. The initial bootstrap set needs no annotation.

Prefer one observable outcome per behaviour. If a behaviour has multiple outcomes, split it or use AND sparingly. Do not describe implementation — describe what a caller can see.

## 3. Scope

- One spec per module (usually one class or one closely-related set of functions in one file).
- Describe observable behaviour only: inputs, outputs, exceptions, log lines, side-effects.
- Only spec what can be verified by a test.

## 4. Lifecycle

- **Add**: append a new `F<n>` in the same PR as the code that introduces it. Add a `(#<n>)` annotation.
- **Modify**: retire the old ID (delete it or note "retired, see F<m>") and add a new `F<m>`. Do not edit existing behaviour wording after it has landed — the ID is the contract.
- **Remove**: delete the behaviour from the spec in the same PR as the code removal.
- Spec changes ship in the **same PR** as the code change they describe.

## 5. Naming

- Spec file: `docs/specs/<module_name>.md` (snake_case, matching the module).
- Test file: `tests/test_<module_name>.py`.
- Behaviour IDs: `F<n>`, numbered per-spec. Retired IDs are not reused.

## 6. Test tagging

Every test that verifies a spec behaviour is tagged with the pytest marker `spec`, parameterised by the **fully qualified** behaviour ID — `<spec_file_stem>.F<n>`:

```python
@pytest.mark.spec("suggestions_engine.F2")
def test_no_standup_rule_fires_on_weekday_morning():
    ...
```

Rules:
- Every numbered behaviour has at least one tagged test.
- A test may cover multiple behaviours; tag it once per behaviour.
- The marker is registered in `pyproject.toml` under `[tool.pytest.ini_options]`.

Discover coverage:
```bash
uv run pytest -m spec --collect-only -q         # every spec-tagged test
grep -rn 'spec("suggestions_engine.F2"' tests   # which test backs F2
```

## 7. When to write a spec

- Before touching a module that doesn't have one — document current behaviour first, then add new behaviour with annotation.
- When introducing a new module.
- Not for trivial scripts or one-off glue code.

## 8. Review checklist

- Every behaviour is observable (not implementation detail).
- Every new behaviour has a passing tagged test in the same PR.
- Behaviour IDs are not reused.
- New post-bootstrap behaviours carry a `(#<n>)` annotation.
