"""Tests for PR↔session linkage on /api/prs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.db import _connect, init_db, upsert_event
from jarvis.sessions_tags import correlate_claude_sessions
from jarvis.web.app import _attach_authoring_sessions


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    c = _connect(db)
    yield c
    c.close()


def _make_session(conn, session_id: str, project: str, branch: str, when: datetime):
    upsert_event(
        conn,
        source="claude_sessions",
        kind="session",
        title=f"[{project}] hi",
        happened_at=when,
        metadata={
            "session_id": session_id,
            "branch": branch,
            "cwd": f"/tmp/{project}",
            "last_message_at": when.isoformat(),
        },
        project=project,
        url=f"claude-session://{session_id}",
    )


def _seed_pr_sub(conn, repo: str, number: int, branch: str):
    from ulid import ULID

    conn.execute(
        """INSERT INTO pr_subscriptions (id, repo, pr_number, branch, subscribed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (str(ULID()), repo, number, branch, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def test_attach_authoring_sessions_orders_newest_first(conn):
    now = datetime.now(UTC)
    _make_session(conn, "old", "jarvis", "feat/x", now - timedelta(days=2))
    _make_session(conn, "new", "jarvis", "feat/x", now)
    _seed_pr_sub(conn, "me/jarvis", 77, "feat/x")
    correlate_claude_sessions(conn)

    subs = [{"repo": "me/jarvis", "pr_number": 77}]
    _attach_authoring_sessions(conn, subs)

    assert subs[0]["authoring_session_ids"] == ["new", "old"]


def test_attach_authoring_sessions_empty_when_no_tag(conn):
    _seed_pr_sub(conn, "me/orphan", 1, "orphan-branch")
    # no sessions touch this branch, so correlator adds no pr: tags
    correlate_claude_sessions(conn)

    subs = [{"repo": "me/orphan", "pr_number": 1}]
    _attach_authoring_sessions(conn, subs)

    assert subs[0]["authoring_session_ids"] == []


def test_attach_authoring_sessions_caps_at_five(conn):
    now = datetime.now(UTC)
    for i in range(7):
        _make_session(conn, f"s{i}", "jarvis", "feat/x", now - timedelta(hours=i))
    _seed_pr_sub(conn, "me/jarvis", 10, "feat/x")
    correlate_claude_sessions(conn)

    subs = [{"repo": "me/jarvis", "pr_number": 10}]
    _attach_authoring_sessions(conn, subs)

    assert len(subs[0]["authoring_session_ids"]) == 5
    # Newest first — s0 is now, s6 is 6h ago
    assert subs[0]["authoring_session_ids"][0] == "s0"
