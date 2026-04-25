"""Tests for jarvis/hooks.py — settings merge + hook event dispatch."""

from __future__ import annotations

import json

import pytest

import jarvis.hooks as hooks
from jarvis.db import _connect, init_db
from jarvis.sessions_tags import effective_tags, get_overrides_map


@pytest.fixture()
def claude_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(hooks, "CLAUDE_SETTINGS_PATH", path)
    yield path


@pytest.fixture()
def db_conn(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    init_db(db)
    monkeypatch.setattr("jarvis.config.DB_PATH", db)
    monkeypatch.setattr("jarvis.db.DB_PATH", db)
    c = _connect(db)
    yield c
    c.close()


def test_install_creates_settings_file(claude_settings):
    added = hooks.install_hooks()
    assert set(added) == {"SessionStart", "PostToolUse", "SessionEnd"}
    data = json.loads(claude_settings.read_text())
    assert "hooks" in data
    # PostToolUse entry is scoped to Bash
    post = data["hooks"]["PostToolUse"][0]
    assert post["matcher"] == "Bash"
    assert post["hooks"][0]["command"] == "jarvis hooks handle"


def test_install_is_idempotent(claude_settings):
    hooks.install_hooks()
    second = hooks.install_hooks()
    assert second == []
    data = json.loads(claude_settings.read_text())
    for event in ("SessionStart", "PostToolUse", "SessionEnd"):
        jarvis_entries = [e for e in data["hooks"][event] if hooks._is_jarvis_entry(e)]
        assert len(jarvis_entries) == 1


def test_uninstall_preserves_other_hooks(claude_settings):
    claude_settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{"hooks": [{"command": "other-thing"}]}],
                }
            }
        )
    )
    hooks.install_hooks()
    removed = hooks.uninstall_hooks()
    assert set(removed) >= {"SessionStart", "PostToolUse", "SessionEnd"}
    data = json.loads(claude_settings.read_text())
    # user's own hook survives
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "other-thing"
    assert "SessionStart" not in data["hooks"]


def test_handle_post_tool_use_captures_pr_link(db_conn):
    hooks._handle_post_tool_use(
        {
            "session_id": "sess-1",
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --fill"},
            "tool_output": "Created PR\nhttps://github.com/me/jarvis/pull/77\n",
            "hook_event_name": "PostToolUse",
        }
    )
    row = get_overrides_map(db_conn).get("sess-1")
    assert row is not None
    assert "pr:me/jarvis#77" in effective_tags(row)
    assert json.loads(row["pr_links"]) == [{"repo": "me/jarvis", "number": 77}]


def test_handle_post_tool_use_ignores_non_pr_bash(db_conn):
    hooks._handle_post_tool_use(
        {
            "session_id": "sess-1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_output": "",
            "hook_event_name": "PostToolUse",
        }
    )
    assert "sess-1" not in get_overrides_map(db_conn)
