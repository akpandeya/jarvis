"""Tests for jarvis/sessions_backfill.py."""

from __future__ import annotations

import json

import pytest

import jarvis.sessions_backfill as backfill
from jarvis.db import _connect, init_db
from jarvis.sessions_tags import effective_tags, get_overrides_map


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    init_db(db)
    claude_dir = tmp_path / "claude-projects"
    claude_dir.mkdir()
    monkeypatch.setattr(backfill, "_CLAUDE_DIR", claude_dir)
    monkeypatch.setattr("jarvis.config.DB_PATH", db)
    monkeypatch.setattr("jarvis.db.DB_PATH", db)
    conn = _connect(db)
    yield conn, claude_dir
    conn.close()


def _write_jsonl(dir_: str | object, name: str, entries: list[dict]) -> None:
    (dir_ / "proj").mkdir(exist_ok=True)
    path = dir_ / "proj" / name
    path.write_text("\n".join(json.dumps(e) for e in entries))


def _bash_tool_use(tid: str, cmd: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}],
        },
    }


def _bash_tool_result(tid: str, output: str, *, structured: bool = False) -> dict:
    if structured:
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tid, "content": ""}],
            },
            "toolUseResult": {"stdout": output, "stderr": ""},
        }
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": output}],
        },
    }


def test_backfill_captures_pr_from_tool_result(sandbox):
    conn, claude_dir = sandbox
    _write_jsonl(
        claude_dir,
        "sess-a.jsonl",
        [
            _bash_tool_use("t1", "gh pr create --title 'x' --body 'y'"),
            _bash_tool_result("t1", "https://github.com/me/jarvis/pull/42\n"),
        ],
    )

    summary = backfill.run_backfill(conn)

    assert summary["links_added"] == 1
    row = get_overrides_map(conn)["sess-a"]
    assert "pr:me/jarvis#42" in effective_tags(row)
    assert json.loads(row["pr_links"]) == [{"repo": "me/jarvis", "number": 42}]


def test_backfill_parses_structured_stdout(sandbox):
    conn, claude_dir = sandbox
    _write_jsonl(
        claude_dir,
        "sess-b.jsonl",
        [
            _bash_tool_use("t1", "gh pr create --fill"),
            _bash_tool_result("t1", "https://github.com/me/jarvis/pull/7", structured=True),
        ],
    )

    backfill.run_backfill(conn)

    row = get_overrides_map(conn)["sess-b"]
    assert "pr:me/jarvis#7" in effective_tags(row)


def test_backfill_ignores_grep_matches(sandbox):
    conn, claude_dir = sandbox
    # This command contains "gh pr create" as a grep literal, not a real call.
    _write_jsonl(
        claude_dir,
        "sess-c.jsonl",
        [
            _bash_tool_use("t1", "grep 'gh pr create' ~/.claude/projects/**/*.jsonl"),
            _bash_tool_result(
                "t1", "some file: gh pr create --title ...\nhttps://github.com/x/y/pull/99\n"
            ),
        ],
    )

    summary = backfill.run_backfill(conn)

    assert summary["links_added"] == 0
    assert "sess-c" not in get_overrides_map(conn)


def test_backfill_is_idempotent(sandbox):
    conn, claude_dir = sandbox
    _write_jsonl(
        claude_dir,
        "sess-d.jsonl",
        [
            _bash_tool_use("t1", "gh pr create"),
            _bash_tool_result("t1", "https://github.com/me/j/pull/1"),
        ],
    )

    first = backfill.run_backfill(conn)
    second = backfill.run_backfill(conn)
    assert first["links_added"] == 1
    assert second["links_added"] == 0
    row = get_overrides_map(conn)["sess-d"]
    assert json.loads(row["pr_links"]) == [{"repo": "me/j", "number": 1}]


def test_backfill_captures_multiple_prs_in_one_session(sandbox):
    conn, claude_dir = sandbox
    _write_jsonl(
        claude_dir,
        "sess-e.jsonl",
        [
            _bash_tool_use("t1", "gh pr create --fill"),
            _bash_tool_result("t1", "https://github.com/me/j/pull/10"),
            _bash_tool_use("t2", "gh pr create --fill"),
            _bash_tool_result("t2", "https://github.com/me/j/pull/11"),
        ],
    )

    backfill.run_backfill(conn)

    row = get_overrides_map(conn)["sess-e"]
    assert {"repo": "me/j", "number": 10} in json.loads(row["pr_links"])
    assert {"repo": "me/j", "number": 11} in json.loads(row["pr_links"])
    tags = effective_tags(row)
    assert "pr:me/j#10" in tags
    assert "pr:me/j#11" in tags
