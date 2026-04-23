"""Tests for jarvis/pr_monitor.py — keyed to docs/specs/pr_monitor.md."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jarvis.pr_monitor import (
    _check_pr_size,
    _ci_cache_key,
    _comments_cache_key,
    _explain_ci_failure,
    _maybe_automerge,
    _run_monitor,
    _sha,
    _summarise_review_comments,
    run_pr_monitor,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _pr(
    number: int = 1,
    title: str = "Fix thing",
    is_draft: bool = False,
    review_decision: str = "APPROVED",
    changed_files: int = 3,
    status_rollup: list | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "isDraft": is_draft,
        "reviewDecision": review_decision,
        "changedFiles": changed_files,
        "statusCheckRollup": status_rollup or [],
        "headRefName": "feat/my-branch",
    }


def _completed_success() -> dict:
    return {
        "__typename": "CheckRun",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "databaseId": 99,
    }


def _completed_failure(run_id: int = 42) -> dict:
    return {
        "__typename": "CheckRun",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "databaseId": run_id,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_sha_returns_16_chars():
    assert len(_sha("hello")) == 16


def test_ci_cache_key_format():
    assert _ci_cache_key("123") == "pr_ci_explained:123"


def test_comments_cache_key_format():
    assert _comments_cache_key(7) == "pr_comments_hash:7"


# ---------------------------------------------------------------------------
# F1: iterates all configured repos
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F1")
def test_run_monitor_iterates_all_repos(db):
    """_run_monitor calls gh pr list for every repo in the list."""
    repos = ["owner/repo-a", "owner/repo-b"]

    def fake_gh_json(*args):
        # Return a single PR for each repo
        if "pr" in args and "list" in args:
            return [_pr(number=1)]
        return None

    with (
        patch("jarvis.pr_monitor._gh_json", side_effect=fake_gh_json) as mock_json,
        patch("jarvis.pr_monitor._explain_ci_failure"),
        patch("jarvis.pr_monitor._summarise_review_comments"),
        patch("jarvis.pr_monitor._maybe_automerge"),
        patch("jarvis.pr_monitor._check_pr_size"),
    ):
        _run_monitor(db, repos)

    # Two calls to gh pr list — one per repo
    list_calls = [c for c in mock_json.call_args_list if "list" in c.args]
    assert len(list_calls) == 2
    repos_called = [c.args[c.args.index("--repo") + 1] for c in list_calls]
    assert set(repos_called) == set(repos)


# ---------------------------------------------------------------------------
# F2: CI failure → LLM explanation → post comment (cached per run_id)
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F2")
def test_explain_ci_failure_posts_comment(db):
    """Posts a PR comment when a CI check fails."""
    pr = _pr(status_rollup=[_completed_failure(run_id=42)])

    with (
        patch("jarvis.pr_monitor._gh") as mock_gh,
        patch("jarvis.pr_monitor._call_claude", return_value="root cause") as mock_llm,
    ):
        # First call: gh run view (log); second call: gh pr comment
        mock_gh.return_value = MagicMock(returncode=0, stdout="build failed\nerror here")
        _explain_ci_failure(db, "owner/repo", pr)

    # LLM was called once
    assert mock_llm.call_count == 1
    # gh pr comment was invoked — args are positional strings, e.g. ("pr", "comment", ...)
    comment_calls = [c for c in mock_gh.call_args_list if "comment" in c.args]
    assert len(comment_calls) == 1


@pytest.mark.spec("pr_monitor.F2")
def test_explain_ci_failure_skips_when_no_failure(db):
    """Does nothing when there are no failing checks."""
    pr = _pr(status_rollup=[_completed_success()])

    with (
        patch("jarvis.pr_monitor._gh") as mock_gh,
        patch("jarvis.pr_monitor._call_claude") as mock_llm,
    ):
        _explain_ci_failure(db, "owner/repo", pr)

    mock_llm.assert_not_called()
    mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# F2 + F7 + F10: second run does NOT re-comment (idempotent, cached)
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F2")
@pytest.mark.spec("pr_monitor.F7")
@pytest.mark.spec("pr_monitor.F10")
def test_explain_ci_failure_idempotent_cached(db):
    """Second run with same run_id skips LLM call and comment."""
    pr = _pr(status_rollup=[_completed_failure(run_id=55)])

    with (
        patch("jarvis.pr_monitor._gh") as mock_gh,
        patch("jarvis.pr_monitor._call_claude", return_value="explanation") as mock_llm,
    ):
        mock_gh.return_value = MagicMock(returncode=0, stdout="error log")
        _explain_ci_failure(db, "owner/repo", pr)
        # Second call — cache hit expected
        _explain_ci_failure(db, "owner/repo", pr)

    # LLM called only once
    assert mock_llm.call_count == 1
    # Comment posted only once — args are positional strings, e.g. ("pr", "comment", ...)
    comment_calls = [c for c in mock_gh.call_args_list if "comment" in c.args]
    assert len(comment_calls) == 1


# ---------------------------------------------------------------------------
# F4: auto-merge when approved + all CI green
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F4")
def test_maybe_automerge_approved_and_green(db):
    """Calls gh pr merge --squash when PR is approved and all checks pass."""
    pr = _pr(
        number=7,
        review_decision="APPROVED",
        is_draft=False,
        status_rollup=[_completed_success()],
    )

    with patch("jarvis.pr_monitor._gh") as mock_gh:
        mock_gh.return_value = MagicMock(returncode=0)
        merged = _maybe_automerge(db, "owner/repo", pr)

    assert merged is True
    # args are positional strings, e.g. ("pr", "merge", "7", "--repo", ..., "--squash")
    merge_calls = [c for c in mock_gh.call_args_list if "merge" in c.args]
    assert len(merge_calls) == 1
    assert "--squash" in merge_calls[0].args
    assert "7" in merge_calls[0].args


@pytest.mark.spec("pr_monitor.F4")
def test_maybe_automerge_skips_draft(db):
    pr = _pr(is_draft=True, review_decision="APPROVED", status_rollup=[_completed_success()])
    with patch("jarvis.pr_monitor._gh") as mock_gh:
        merged = _maybe_automerge(db, "owner/repo", pr)
    assert merged is False
    mock_gh.assert_not_called()


@pytest.mark.spec("pr_monitor.F4")
def test_maybe_automerge_skips_not_approved(db):
    pr = _pr(review_decision="REVIEW_REQUIRED", status_rollup=[_completed_success()])
    with patch("jarvis.pr_monitor._gh") as mock_gh:
        merged = _maybe_automerge(db, "owner/repo", pr)
    assert merged is False
    mock_gh.assert_not_called()


@pytest.mark.spec("pr_monitor.F4")
def test_maybe_automerge_skips_failing_ci(db):
    pr = _pr(
        review_decision="APPROVED",
        status_rollup=[_completed_failure()],
    )
    with patch("jarvis.pr_monitor._gh") as mock_gh:
        merged = _maybe_automerge(db, "owner/repo", pr)
    assert merged is False
    mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# F5: oversized PR — deterministic, no LLM
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F5")
def test_check_pr_size_flags_oversized(db):
    """Surfaces a suggestion for PRs with too many changed files (no LLM)."""
    big_pr = _pr(number=10, changed_files=25)

    with patch("jarvis.pr_monitor._call_claude") as mock_llm:
        _check_pr_size(db, "owner/repo", big_pr, max_files=20)

    mock_llm.assert_not_called()
    row = db.execute("SELECT * FROM suggestions WHERE rule_id='pr_too_large_10'").fetchone()
    assert row is not None
    assert "25" in row["message"]


@pytest.mark.spec("pr_monitor.F5")
def test_check_pr_size_skips_small_pr(db):
    small_pr = _pr(changed_files=5)
    _check_pr_size(db, "owner/repo", small_pr, max_files=20)
    row = db.execute("SELECT * FROM suggestions WHERE rule_id='pr_too_large_1'").fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# F7 + F10: review comment summary is cached per comment hash
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F7")
@pytest.mark.spec("pr_monitor.F10")
def test_summarise_review_comments_cached(db):
    """Second run with same comments does not call LLM again."""
    comments = [
        {"user": {"login": "reviewer"}, "path": "foo.py", "body": "Needs a test"},
    ]

    with (
        patch("jarvis.pr_monitor._gh_json", return_value=comments),
        patch("jarvis.pr_monitor._call_claude", return_value="summary") as mock_llm,
    ):
        _summarise_review_comments(db, "owner/repo", _pr(number=3))
        _summarise_review_comments(db, "owner/repo", _pr(number=3))

    assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# F9: exits cleanly when no GitHub token configured
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F9")
def test_run_pr_monitor_exits_cleanly_without_token(monkeypatch, caplog):
    """run_pr_monitor logs a warning and returns without error when no token."""
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: None)

    with patch("jarvis.pr_monitor._run_monitor") as mock_inner:
        run_pr_monitor()

    mock_inner.assert_not_called()


@pytest.mark.spec("pr_monitor.F9")
def test_run_pr_monitor_exits_cleanly_no_gh_cli(monkeypatch):
    """run_pr_monitor returns without error when gh CLI is not installed."""
    import shutil

    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: "fake-token")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    with patch("jarvis.pr_monitor._run_monitor") as mock_inner:
        run_pr_monitor()

    mock_inner.assert_not_called()
