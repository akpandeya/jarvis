"""Tests for jarvis/integrations/claude_sessions.py — keyed to docs/specs/claude_sessions.md."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.integrations.claude_sessions import ClaudeSessions, _parse_session


def _write_session(tmp_path: Path, entries: list[dict], subdir: str = "proj") -> Path:
    d = tmp_path / subdir
    d.mkdir(exist_ok=True)
    f = d / "abc123.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in entries))
    return f


def _user_entry(text: str, ts: str, slug: str = "test-slug", branch: str = "main") -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
        "timestamp": ts,
        "slug": slug,
        "gitBranch": branch,
        "cwd": "/some/path",
        "sessionId": "abc123",
    }


def _assistant_entry(text: str) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


@pytest.mark.spec("claude_sessions.F2")
def test_parse_session_returns_single_event(tmp_path):
    ts = datetime.now(UTC).isoformat()
    f = _write_session(
        tmp_path,
        [
            _user_entry("Fix the bug", ts),
            _assistant_entry("I will fix it"),
        ],
    )
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is not None
    assert event.source == "claude_sessions"
    assert event.kind == "session"


@pytest.mark.spec("claude_sessions.F3")
def test_parse_session_skips_old_session(tmp_path):
    old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    f = _write_session(tmp_path, [_user_entry("Old work", old_ts)])
    since = datetime.now(UTC) - timedelta(days=7)
    event = _parse_session(f, since)
    assert event is None


@pytest.mark.spec("claude_sessions.F4")
def test_event_title_includes_project_and_message(tmp_path):
    ts = datetime.now(UTC).isoformat()
    f = _write_session(
        tmp_path, [_user_entry("Add new feature", ts)], subdir="-Users-me-code-myproject"
    )
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is not None
    assert "myproject" in event.title
    assert "Add new feature" in event.title


@pytest.mark.spec("claude_sessions.F4")
def test_event_title_truncates_at_100_chars(tmp_path):
    ts = datetime.now(UTC).isoformat()
    long_msg = "x" * 200
    f = _write_session(tmp_path, [_user_entry(long_msg, ts)])
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is not None
    # title = "[proj] " + first 100 chars
    assert len(event.title) <= len("[proj] ") + 100 + 10  # small slack for project name


@pytest.mark.spec("claude_sessions.F5")
def test_event_body_is_first_assistant_response(tmp_path):
    ts = datetime.now(UTC).isoformat()
    f = _write_session(
        tmp_path,
        [
            _user_entry("Question", ts),
            _assistant_entry("The answer is 42"),
        ],
    )
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is not None
    assert event.body == "The answer is 42"


@pytest.mark.spec("claude_sessions.F6")
def test_health_check_false_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.integrations.claude_sessions._CLAUDE_DIR", tmp_path / "nonexistent")
    c = ClaudeSessions()
    assert c.health_check() is False


@pytest.mark.spec("claude_sessions.F6")
def test_health_check_true_when_dir_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.integrations.claude_sessions._CLAUDE_DIR", tmp_path)
    c = ClaudeSessions()
    assert c.health_check() is True


@pytest.mark.spec("claude_sessions.F7")
def test_parse_session_returns_none_for_empty_file(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("")
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is None


@pytest.mark.spec("claude_sessions.F7")
def test_parse_session_skips_corrupt_lines(tmp_path):
    ts = datetime.now(UTC).isoformat()
    f = tmp_path / "corrupt.jsonl"
    f.write_text(
        "not json at all\n"
        + json.dumps(_user_entry("Valid", ts))
        + "\n"
        + json.dumps(_assistant_entry("Ok"))
        + "\n"
    )
    since = datetime.now(UTC) - timedelta(days=1)
    event = _parse_session(f, since)
    assert event is not None


@pytest.mark.spec("claude_sessions.F1")
def test_fetch_since_skips_subagent_files(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.integrations.claude_sessions._CLAUDE_DIR", tmp_path)
    ts = datetime.now(UTC).isoformat()
    # Regular session
    reg_dir = tmp_path / "myproject"
    reg_dir.mkdir()
    (reg_dir / "sess1.jsonl").write_text(json.dumps(_user_entry("Real session", ts)))
    # Subagent file (should be skipped)
    sub_dir = tmp_path / "myproject" / "subagents"
    sub_dir.mkdir()
    (sub_dir / "agent.jsonl").write_text(json.dumps(_user_entry("Subagent", ts)))

    c = ClaudeSessions()
    since = datetime.now(UTC) - timedelta(days=1)
    events = c.fetch_since(since)
    sources = [e.title for e in events]
    assert any("Real session" in t for t in sources)
    assert not any("Subagent" in t for t in sources)
