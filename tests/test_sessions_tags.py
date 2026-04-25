"""Tests for jarvis/sessions_tags.py — session overrides, correlator, patch semantics."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from jarvis.db import _connect, init_db, upsert_event
from jarvis.sessions_tags import (
    apply_patch,
    correlate_claude_sessions,
    effective_tags,
    get_overrides_map,
)


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    c = _connect(db)
    yield c
    c.close()


def _make_session(conn, session_id: str, *, project: str, branch: str, cwd: str):
    upsert_event(
        conn,
        source="claude_sessions",
        kind="session",
        title=f"[{project}] hello",
        happened_at=datetime.now(UTC),
        metadata={
            "session_id": session_id,
            "branch": branch,
            "cwd": cwd,
            "last_message_at": datetime.now(UTC).isoformat(),
        },
        project=project,
    )


def test_correlator_emits_repo_and_jarvis_tags(conn):
    _make_session(conn, "s1", project="jarvis", branch="main", cwd="/Users/x/code/jarvis")
    _make_session(conn, "s2", project="other", branch="feat/x", cwd="/Users/x/code/other")

    correlate_claude_sessions(conn)

    overrides = get_overrides_map(conn)
    s1_tags = effective_tags(overrides["s1"])
    s2_tags = effective_tags(overrides["s2"])
    assert "repo:jarvis" in s1_tags
    assert "jarvis-involved" in s1_tags
    assert "repo:other" in s2_tags
    assert "jarvis-involved" not in s2_tags


def test_correlator_links_pr_by_branch(conn):
    _make_session(conn, "s1", project="jarvis", branch="feat/x", cwd="/x")
    conn.execute(
        """INSERT INTO pr_subscriptions (id, repo, pr_number, branch, subscribed_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("p1", "me/jarvis", 42, "feat/x", datetime.now(UTC).isoformat()),
    )
    conn.commit()

    correlate_claude_sessions(conn)

    row = get_overrides_map(conn)["s1"]
    tags = effective_tags(row)
    assert "pr:me/jarvis#42" in tags
    assert json.loads(row["pr_links"]) == [{"repo": "me/jarvis", "number": 42}]


def test_correlator_preserves_manual_fields(conn):
    _make_session(conn, "s1", project="jarvis", branch="main", cwd="/x")
    # Seed with user edits
    apply_patch(conn, "s1", display_title="Renamed", add_tags=["custom"])
    # Also archive
    apply_patch(conn, "s1", archived=True)

    correlate_claude_sessions(conn)

    row = get_overrides_map(conn)["s1"]
    assert row["display_title"] == "Renamed"
    assert row["archived"] == 1
    tags = effective_tags(row)
    assert "custom" in tags
    assert "repo:jarvis" in tags


def test_apply_patch_remove_auto_tag_goes_to_removed(conn):
    _make_session(conn, "s1", project="jarvis", branch="main", cwd="/x")
    correlate_claude_sessions(conn)
    apply_patch(conn, "s1", remove_tags=["repo:jarvis"])
    row = get_overrides_map(conn)["s1"]
    assert "repo:jarvis" in json.loads(row["removed_tags"])
    assert "repo:jarvis" not in effective_tags(row)
    # Re-adding pulls it back out of removed_tags.
    apply_patch(conn, "s1", add_tags=["repo:jarvis"])
    row = get_overrides_map(conn)["s1"]
    assert "repo:jarvis" not in json.loads(row["removed_tags"])
    assert "repo:jarvis" in effective_tags(row)


def test_apply_patch_archive_roundtrip(conn):
    _make_session(conn, "s1", project="jarvis", branch="main", cwd="/x")
    apply_patch(conn, "s1", archived=True)
    assert get_overrides_map(conn)["s1"]["archived"] == 1
    apply_patch(conn, "s1", archived=False)
    assert get_overrides_map(conn)["s1"]["archived"] == 0
