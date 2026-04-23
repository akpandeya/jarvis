"""Tests for jarvis/pr_monitor.py — keyed to docs/specs/pr_monitor.md."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from jarvis.pr_monitor import (
    _check_ci_failure,
    _check_pr_size,
    _check_ready_to_merge,
    _check_review_comments,
    _check_staging_deploy,
    _get_cache,
    _set_cache,
    _sha,
    list_open_prs,
    run_monitor,
)


def _pr(number=1, title="Fix thing", draft=False, changed_files=3, additions=50, deletions=20):
    return {
        "number": number,
        "title": title,
        "draft": draft,
        "head": {"sha": "abc123"},
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
        "html_url": f"https://github.com/owner/repo/pull/{number}",
        "user": {"login": "author"},
    }


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def test_cache_round_trip(db):
    _set_cache(db, "ci_diagnosis", "deadbeef", "the diagnosis")
    result = _get_cache(db, "ci_diagnosis", "deadbeef")
    assert result == "the diagnosis"


def test_cache_miss_returns_none(db):
    assert _get_cache(db, "ci_diagnosis", "notexist") is None


def test_sha_returns_16_chars():
    assert len(_sha("hello")) == 16


# ---------------------------------------------------------------------------
# F2 + F8: CI failure signal with LLM caching
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F2")
def test_check_ci_failure_returns_suggestion_on_failure(db):
    check_runs = {"check_runs": [{"id": 1, "name": "unit-tests", "conclusion": "failure"}]}
    jobs = {"jobs": [{"id": 10, "name": "unit-tests", "conclusion": "failure", "steps": []}]}

    with (
        patch("jarvis.pr_monitor._get") as mock_get,
        patch("jarvis.pr_monitor._call_claude", return_value="root cause here"),
        patch("httpx.get") as mock_http,
    ):
        mock_get.side_effect = lambda url, token, **kw: check_runs if "check-runs" in url else jobs
        mock_http.return_value = MagicMock(text="build failed: ImportError")
        result = _check_ci_failure(db, "owner/repo", _pr(), "tok")

    assert result is not None
    assert "unit-tests" in result.message
    assert result.priority == 90


@pytest.mark.spec("pr_monitor.F2")
def test_check_ci_failure_returns_none_when_no_failure(db):
    check_runs = {"check_runs": [{"id": 1, "name": "unit-tests", "conclusion": "success"}]}
    with patch("jarvis.pr_monitor._get", return_value=check_runs):
        result = _check_ci_failure(db, "owner/repo", _pr(), "tok")
    assert result is None


@pytest.mark.spec("pr_monitor.F8")
def test_check_ci_failure_uses_cache(db):
    check_runs = {"check_runs": [{"id": 1, "name": "tests", "conclusion": "failure"}]}
    jobs = {"jobs": [{"id": 10, "name": "tests", "conclusion": "failure", "steps": []}]}

    with (
        patch("jarvis.pr_monitor._get") as mock_get,
        patch("jarvis.pr_monitor._call_claude", return_value="diagnosis") as mock_llm,
        patch("httpx.get") as mock_http,
    ):
        mock_get.side_effect = lambda url, token, **kw: check_runs if "check-runs" in url else jobs
        mock_http.return_value = MagicMock(text="error log")
        _check_ci_failure(db, "owner/repo", _pr(), "tok")
        _check_ci_failure(db, "owner/repo", _pr(), "tok")

    assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# F3: suggestion action is jarvis pr-fix
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F3")
def test_ci_failure_action_is_pr_fix(db):
    check_runs = {"check_runs": [{"id": 1, "name": "ci", "conclusion": "failure"}]}
    jobs = {"jobs": [{"id": 10, "name": "ci", "conclusion": "failure", "steps": []}]}

    with (
        patch("jarvis.pr_monitor._get") as mock_get,
        patch("jarvis.pr_monitor._call_claude", return_value="fix suggestion"),
        patch("httpx.get") as mock_http,
    ):
        mock_get.side_effect = lambda url, token, **kw: check_runs if "check-runs" in url else jobs
        mock_http.return_value = MagicMock(text="log")
        result = _check_ci_failure(db, "owner/repo", _pr(number=42), "tok")

    assert result is not None
    assert "pr-fix" in result.action
    assert "42" in result.action


# ---------------------------------------------------------------------------
# F4 + F8: review comments signal with LLM caching
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F4")
def test_check_review_comments_new_comments_returns_suggestion(db):
    now = datetime.now(UTC)
    comments = [
        {
            "user": {"login": "reviewer"},
            "path": "src/foo.py",
            "line": 10,
            "body": "This needs a test",
            "created_at": now.isoformat().replace("+00:00", "Z"),
        }
    ]
    with (
        patch("jarvis.pr_monitor._get", return_value=comments),
        patch("jarvis.pr_monitor._call_claude", return_value="summary"),
    ):
        result = _check_review_comments(db, "owner/repo", _pr(), "tok")

    assert result is not None
    assert result.priority == 80


@pytest.mark.spec("pr_monitor.F4")
def test_check_review_comments_old_comments_returns_none(db):
    old_time = (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    comments = [
        {
            "user": {"login": "reviewer"},
            "path": "src/foo.py",
            "line": 10,
            "body": "Old comment",
            "created_at": old_time,
        }
    ]
    with patch("jarvis.pr_monitor._get", return_value=comments):
        result = _check_review_comments(db, "owner/repo", _pr(), "tok")
    assert result is None


@pytest.mark.spec("pr_monitor.F8")
def test_check_review_comments_cached(db):
    now = datetime.now(UTC)
    comments = [
        {
            "user": {"login": "reviewer"},
            "path": "foo.py",
            "line": 1,
            "body": "Cached comment",
            "created_at": now.isoformat().replace("+00:00", "Z"),
        }
    ]
    with (
        patch("jarvis.pr_monitor._get", return_value=comments),
        patch("jarvis.pr_monitor._call_claude", return_value="cached summary") as mock_llm,
    ):
        _check_review_comments(db, "owner/repo", _pr(), "tok")
        _check_review_comments(db, "owner/repo", _pr(), "tok")

    assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# F5: ready to merge
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F5")
def test_check_ready_to_merge_approved_and_green(db):
    reviews = [{"user": {"login": "reviewer"}, "state": "APPROVED"}]
    check_runs = {"check_runs": [{"conclusion": "success"}]}

    def fake_get(url, token, **kw):
        if "reviews" in url:
            return reviews
        if "check-runs" in url:
            return check_runs
        return None

    with patch("jarvis.pr_monitor._get", side_effect=fake_get):
        result = _check_ready_to_merge(db, "owner/repo", _pr(), "tok")

    assert result is not None
    assert result.priority == 85
    assert "merge" in result.action


@pytest.mark.spec("pr_monitor.F5")
def test_check_ready_to_merge_not_all_approved_returns_none(db):
    reviews = [
        {"user": {"login": "r1"}, "state": "APPROVED"},
        {"user": {"login": "r2"}, "state": "CHANGES_REQUESTED"},
    ]
    with patch("jarvis.pr_monitor._get", return_value=reviews):
        result = _check_ready_to_merge(db, "owner/repo", _pr(), "tok")
    assert result is None


@pytest.mark.spec("pr_monitor.F5")
def test_check_ready_to_merge_draft_returns_none(db):
    result = _check_ready_to_merge(db, "owner/repo", _pr(draft=True), "tok")
    assert result is None


# ---------------------------------------------------------------------------
# F6 + F12: oversized PR
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F6")
def test_check_pr_size_oversized_returns_suggestion(db):
    big_pr = _pr(changed_files=15, additions=300, deletions=300)
    with (
        patch("httpx.get") as mock_http,
        patch("jarvis.pr_monitor._call_claude", return_value="split into 3 PRs"),
    ):
        mock_http.return_value = MagicMock(text="diff content")
        result = _check_pr_size(db, "owner/repo", big_pr, "tok", max_files=10, max_lines=500)

    assert result is not None
    assert "15 files" in result.message


@pytest.mark.spec("pr_monitor.F12")
def test_check_pr_size_within_defaults_returns_none(db):
    small_pr = _pr(changed_files=3, additions=100, deletions=50)
    result = _check_pr_size(db, "owner/repo", small_pr, "tok")
    assert result is None


@pytest.mark.spec("pr_monitor.F12")
def test_default_thresholds_are_10_files_500_lines(db):
    from jarvis.pr_monitor import _DEFAULT_MAX_FILES, _DEFAULT_MAX_LINES

    assert _DEFAULT_MAX_FILES == 10
    assert _DEFAULT_MAX_LINES == 500


# ---------------------------------------------------------------------------
# F7: staging deploy
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F7")
def test_check_staging_deploy_returns_suggestion(db):
    deployments = [{"id": 1, "environment": "staging-eu"}]
    with patch("jarvis.pr_monitor._get", return_value=deployments):
        result = _check_staging_deploy(db, "owner/repo", _pr(), "tok")

    assert result is not None
    assert "staging" in result.message.lower()
    assert result.priority == 75


@pytest.mark.spec("pr_monitor.F7")
def test_check_staging_deploy_one_shot(db):
    deployments = [{"id": 99, "environment": "staging"}]
    with patch("jarvis.pr_monitor._get", return_value=deployments):
        first = _check_staging_deploy(db, "owner/repo", _pr(), "tok")
        # Mark it as promoted
        _set_cache(db, "staging_promoted", "99", "1")
        second = _check_staging_deploy(db, "owner/repo", _pr(), "tok")

    assert first is not None
    assert second is None


# ---------------------------------------------------------------------------
# F1 + F9: run_monitor iterates accounts and records activity
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F1")
def test_run_monitor_skips_missing_token(db, monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: None)
    counts = run_monitor(db, account_keys=["missing_key"])
    assert counts["prs_checked"] == 0


@pytest.mark.spec("pr_monitor.F9")
def test_run_monitor_records_activity_log(db, monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: "fake-token")

    with patch("jarvis.pr_monitor._get") as mock_get:
        mock_get.return_value = []
        run_monitor(db, account_keys=["github_token"], repos=["owner/repo"])

    row = db.execute(
        "SELECT * FROM activity_log WHERE source='pr_monitor' AND kind='monitor_run'"
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# F10: list_open_prs returns flat list
# ---------------------------------------------------------------------------


@pytest.mark.spec("pr_monitor.F10")
def test_list_open_prs_returns_pr_fields(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: "fake-token")

    pr_data = {
        "number": 7,
        "title": "Add feature",
        "user": {"login": "dev"},
        "draft": False,
        "html_url": "https://github.com/o/r/pull/7",
        "changed_files": 4,
        "additions": 80,
        "deletions": 10,
    }
    check_runs = {"check_runs": [{"conclusion": "success"}]}

    def fake_get(url, token, **kw):
        if "check-runs" in url:
            return check_runs
        return [pr_data]

    with patch("jarvis.pr_monitor._get", side_effect=fake_get):
        result = list_open_prs(account_keys=["github_token"], repos=["o/r"])

    assert len(result) == 1
    assert result[0]["number"] == 7
    assert result[0]["ci"] == "passing"
    assert result[0]["repo"] == "o/r"
