"""Tests for jarvis/memory.py — keyed to docs/specs/memory.md."""

import pytest

from jarvis.db import save_session

# ---------------------------------------------------------------------------
# remember_note (F7) — no Claude call, just saves directly
# ---------------------------------------------------------------------------


@pytest.mark.spec("memory.F7")
def test_remember_note_saves_without_claude(tmp_path, monkeypatch):
    import jarvis.memory as mem_mod
    from jarvis.db import _connect, init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = _connect(db_path)
    monkeypatch.setattr(mem_mod, "get_db", lambda: _connect(db_path))

    mem_mod.remember_note("deploy jarvis to prod", project="jarvis")

    row = conn.execute("SELECT context, project FROM sessions LIMIT 1").fetchone()
    assert row["context"] == "deploy jarvis to prod"
    assert row["project"] == "jarvis"
    conn.close()


# ---------------------------------------------------------------------------
# capture_session (F2) — no events → no Claude call
# ---------------------------------------------------------------------------


@pytest.mark.spec("memory.F2")
def test_capture_session_no_events_skips_claude(db, monkeypatch):
    import jarvis.memory as mem_mod

    monkeypatch.setattr(mem_mod, "get_db", lambda: db)
    claude_called = []
    monkeypatch.setattr(mem_mod, "_call_claude", lambda *a, **kw: claude_called.append(1) or "")

    summary = mem_mod.capture_session()
    assert claude_called == []
    assert "no recent activity" in summary.lower()


# ---------------------------------------------------------------------------
# generate_context (F6) — no sessions or events → no Claude call
# ---------------------------------------------------------------------------


@pytest.mark.spec("memory.F6")
def test_generate_context_no_data_skips_claude(db, monkeypatch):
    import jarvis.memory as mem_mod

    monkeypatch.setattr(mem_mod, "get_db", lambda: db)
    claude_called = []
    monkeypatch.setattr(mem_mod, "_call_claude", lambda *a, **kw: claude_called.append(1) or "")

    result = mem_mod.generate_context()
    assert claude_called == []
    assert "no recent" in result.lower()


# ---------------------------------------------------------------------------
# generate_context (F4) — includes sessions and events in prompt
# ---------------------------------------------------------------------------


@pytest.mark.spec("memory.F4")
def test_generate_context_passes_sessions_and_events_to_claude(db, monkeypatch):
    import uuid
    from datetime import UTC, datetime

    import jarvis.memory as mem_mod
    from jarvis.db import upsert_event

    monkeypatch.setattr(mem_mod, "get_db", lambda: db)

    save_session(db, context="Fixed auth bug in jarvis")
    upsert_event(
        db,
        source="github",
        kind="commit",
        title="Fix auth token expiry",
        happened_at=datetime.now(UTC),
        url=str(uuid.uuid4()),
    )

    captured = {}

    def fake_claude(system, user_msg):
        captured["system"] = system
        captured["user"] = user_msg
        return "mock context"

    monkeypatch.setattr(mem_mod, "_call_claude", fake_claude)
    mem_mod.generate_context()

    assert "Fixed auth bug" in captured.get("user", "")
    assert "Fix auth token expiry" in captured.get("user", "")
