"""Tests for jarvis/evolve.py — keyed to docs/specs/evolve.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jarvis.db import upsert_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_event(db, source="github"):
    import uuid

    return upsert_event(
        db,
        source=source,
        kind="commit",
        title="work item",
        happened_at=datetime.now(UTC),
        url=str(uuid.uuid4()),
    )


def _sample_items():
    return [
        {"feature": "jarvis evolve", "phase": "Phase 7", "rationale": "high usage", "score": 90},
        {
            "feature": "Android integration",
            "phase": "Phase 8+",
            "rationale": "low usage",
            "score": 20,
        },
    ]


def _raw_llm_response(items=None):
    return json.dumps(items or _sample_items())


# ---------------------------------------------------------------------------
# F1 — calls LLM with TODO content and signals
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F1")
def test_llm_called_with_todo_and_signals(db, tmp_path, monkeypatch):
    """WHEN evolve runs with activity data THEN LLM is called with TODO content and signals."""
    _insert_event(db)

    # Point get_db to our test db
    monkeypatch.setattr("jarvis.evolve.get_db", lambda: db)

    todo_content = "# TODO\n\n- Feature A\n- Feature B\n"
    todo_path = tmp_path / "TODO.md"
    todo_path.write_text(todo_content)
    monkeypatch.setattr("jarvis.evolve._TODO_PATH", todo_path)

    captured_calls = []

    def fake_call_llm(todo, signals):
        captured_calls.append({"todo": todo, "signals": signals})
        return _raw_llm_response()

    monkeypatch.setattr("jarvis.evolve._call_llm", fake_call_llm)

    from jarvis.evolve import run_evolve

    run_evolve(fresh=True)

    assert len(captured_calls) == 1
    assert "TODO" in captured_calls[0]["todo"]
    assert "signals" in str(captured_calls[0]["signals"]) or isinstance(
        captured_calls[0]["signals"], dict
    )


# ---------------------------------------------------------------------------
# F2 — signals include command_frequency and top_urls
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F2")
def test_signals_include_command_frequency_and_top_urls(db, monkeypatch):
    """WHEN signals are collected THEN they include top commands and top URL domains."""
    from jarvis.db import insert_activity

    # Insert some CLI activity
    insert_activity(
        db,
        source="jarvis_cli",
        kind="command",
        happened_at=datetime.now(UTC),
        title="standup",
    )
    insert_activity(
        db,
        source="jarvis_cli",
        kind="command",
        happened_at=datetime.now(UTC),
        title="standup",
    )

    # Insert a Firefox event
    upsert_event(
        db,
        source="firefox",
        kind="visit",
        title="GitHub",
        happened_at=datetime.now(UTC),
        url="https://github.com/foo/bar",
    )

    from jarvis.evolve import _collect_signals

    signals = _collect_signals(db)

    assert "top_commands" in signals
    assert "top_url_domains" in signals
    assert "source_distribution" in signals

    # standup should appear in top commands
    cmd_names = [c[0] for c in signals["top_commands"]]
    assert "standup" in cmd_names


# ---------------------------------------------------------------------------
# F5 — second call within 24h uses cache
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F5")
def test_cache_used_within_24h(tmp_path, monkeypatch):
    """WHEN a result was cached less than 24h ago THEN the second call returns cached data."""
    from jarvis.db import _connect, init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Insert activity so _has_activity returns True
    conn0 = _connect(db_path)
    _insert_event(conn0)
    conn0.close()

    # get_db returns a fresh open connection each call (since run_evolve closes it)
    monkeypatch.setattr("jarvis.evolve.get_db", lambda: _connect(db_path))

    todo_path = tmp_path / "TODO.md"
    todo_path.write_text("# TODO\n- Feature A\n")
    monkeypatch.setattr("jarvis.evolve._TODO_PATH", todo_path)

    llm_call_count = [0]

    def fake_call_llm(todo, signals):
        llm_call_count[0] += 1
        return _raw_llm_response()

    monkeypatch.setattr("jarvis.evolve._call_llm", fake_call_llm)

    from jarvis.evolve import run_evolve

    # First call — should hit LLM
    run_evolve(fresh=True)
    assert llm_call_count[0] == 1

    # Second call — should use cache
    run_evolve(fresh=False)
    assert llm_call_count[0] == 1  # no additional LLM call


# ---------------------------------------------------------------------------
# F6 — --fresh bypasses the cache
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F6")
def test_fresh_bypasses_cache(tmp_path, monkeypatch):
    """WHEN --fresh is passed THEN the cache is ignored and LLM is called again."""
    from jarvis.db import _connect, init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn0 = _connect(db_path)
    _insert_event(conn0)
    conn0.close()

    monkeypatch.setattr("jarvis.evolve.get_db", lambda: _connect(db_path))

    todo_path = tmp_path / "TODO.md"
    todo_path.write_text("# TODO\n- Feature A\n")
    monkeypatch.setattr("jarvis.evolve._TODO_PATH", todo_path)

    llm_call_count = [0]

    def fake_call_llm(todo, signals):
        llm_call_count[0] += 1
        return _raw_llm_response()

    monkeypatch.setattr("jarvis.evolve._call_llm", fake_call_llm)

    from jarvis.evolve import run_evolve

    # Populate the cache
    run_evolve(fresh=True)
    assert llm_call_count[0] == 1

    # Call with --fresh — must call LLM again
    run_evolve(fresh=True)
    assert llm_call_count[0] == 2


# ---------------------------------------------------------------------------
# F7 — --create-pr writes spec file and calls gh
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F7")
def test_create_pr_writes_spec_and_calls_gh(tmp_path, monkeypatch):
    """WHEN --create-pr is passed THEN a stub spec is written and gh pr create is called."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    monkeypatch.setattr("jarvis.evolve._SPECS_DIR", specs_dir)

    # Fake repo root so git commands use tmp_path
    monkeypatch.setattr(
        "jarvis.evolve.Path",
        lambda *args, **kwargs: Path(*args, **kwargs),
    )

    called_commands = []

    def fake_run(cmd, **kwargs):
        called_commands.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = "https://github.com/foo/bar/pull/99"
        result.stderr = ""
        return result

    monkeypatch.setattr("jarvis.evolve.subprocess.run", fake_run)

    from jarvis.evolve import _create_pr

    _create_pr("My Cool Feature")

    # Spec file should have been written
    spec_file = specs_dir / "my_cool_feature.md"
    assert spec_file.exists(), f"Expected spec at {spec_file}"
    content = spec_file.read_text()
    assert "My Cool Feature" in content
    assert "F1" in content

    # gh pr create should have been called
    gh_calls = [c for c in called_commands if "gh" in c]
    assert any("pr" in str(c) and "create" in str(c) for c in gh_calls), (
        f"gh pr create not found in {called_commands}"
    )


# ---------------------------------------------------------------------------
# F8 — no activity → helpful message, no LLM call
# ---------------------------------------------------------------------------


@pytest.mark.spec("evolve.F8")
def test_no_activity_prints_message_no_llm(db, monkeypatch):
    """WHEN no activity data exists THEN a helpful message is printed and LLM is not called."""
    monkeypatch.setattr("jarvis.evolve.get_db", lambda: db)

    llm_called = [False]

    def fake_call_llm(todo, signals):
        llm_called[0] = True
        return _raw_llm_response()

    monkeypatch.setattr("jarvis.evolve._call_llm", fake_call_llm)

    # Capture console output by patching the console
    console_messages = []

    def fake_console_print(msg, **kwargs):
        console_messages.append(str(msg))

    monkeypatch.setattr("jarvis.evolve.console.print", fake_console_print)

    from jarvis.evolve import run_evolve

    run_evolve(fresh=True)

    assert not llm_called[0], "LLM should not be called when no activity data exists"
    assert any("no activity" in m.lower() or "ingest" in m.lower() for m in console_messages), (
        f"Expected helpful message, got: {console_messages}"
    )
