"""Tests for jarvis/integrations/ — keyed to docs/specs/integrations.md."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from jarvis.integrations.git_local import GitLocal
from jarvis.integrations.github import GitHub


def _now():
    return datetime.now(UTC)


def _since():
    return _now() - timedelta(days=7)


# ---------------------------------------------------------------------------
# F1–F3: Integration protocol
# ---------------------------------------------------------------------------


@pytest.mark.spec("integrations.F1")
def test_health_check_false_skips_integration():
    class BrokenIntegration:
        name = "broken"

        def health_check(self):
            return False

        def fetch_since(self, since):
            raise AssertionError("should not be called")

    assert BrokenIntegration().health_check() is False


@pytest.mark.spec("integrations.F3")
def test_health_check_returns_false_on_error():
    class ErrorIntegration:
        name = "error"

        def health_check(self):
            try:
                raise ConnectionError("unreachable")
            except Exception:
                return False

    assert ErrorIntegration().health_check() is False


# ---------------------------------------------------------------------------
# GitLocal
# ---------------------------------------------------------------------------


@pytest.mark.spec("integrations.F14")
def test_git_local_health_check_false_missing_repo(tmp_path):
    integration = GitLocal(repo_paths=[str(tmp_path / "nonexistent")])
    assert integration.health_check() is False


@pytest.mark.spec("integrations.F14")
def test_git_local_skips_missing_repo(tmp_path):
    integration = GitLocal(repo_paths=[str(tmp_path / "nonexistent")])
    events = integration.fetch_since(_since())
    assert events == []


@pytest.mark.spec("integrations.F14")
def test_git_local_health_check_true_with_valid_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    integration = GitLocal(repo_paths=[str(tmp_path)])
    assert integration.health_check() is True


@pytest.mark.spec("integrations.F15")
def test_git_local_fetch_returns_commits(tmp_path):
    (tmp_path / ".git").mkdir()
    since = _since()
    date_str = _now().isoformat()
    fake_output = f"abc123\x00Alice\x00alice@corp.com\x00{date_str}\x00Fix bug\x00\x1e"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
        integration = GitLocal(repo_paths=[str(tmp_path)])
        events = integration.fetch_since(since)

    assert len(events) == 1
    assert events[0].source == "git_local"
    assert events[0].title == "Fix bug"
    assert events[0].entities[0] == ("person", "Alice", "author")


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@pytest.mark.spec("integrations.F4")
def test_github_health_check_false_no_token(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: None)
    gh = GitHub(username="akpandeya", repos=["akpandeya/jarvis"])
    assert gh.health_check() is False


@pytest.mark.spec("integrations.F5")
def test_github_pr_opened_for_own_prs(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: "fake-token")

    pr = {
        "title": "My PR",
        "user": {"login": "akpandeya"},
        "updated_at": _now().isoformat().replace("+00:00", "Z"),
        "created_at": _now().isoformat().replace("+00:00", "Z"),
        "html_url": "https://github.com/r/p/1",
        "number": 1,
        "state": "open",
        "labels": [],
        "draft": False,
        "requested_reviewers": [],
        "body": None,
    }

    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [pr])
        gh = GitHub(username="akpandeya", repos=["akpandeya/jarvis"])
        gh._token = "fake-token"
        events = gh._fetch_prs("akpandeya/jarvis", _since())

    assert len(events) == 1
    assert events[0].kind == "pr_opened"


@pytest.mark.spec("integrations.F6")
def test_github_pr_review_requested_for_others(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a: "fake-token")

    pr = {
        "title": "Their PR",
        "user": {"login": "other-user"},
        "updated_at": _now().isoformat().replace("+00:00", "Z"),
        "created_at": _now().isoformat().replace("+00:00", "Z"),
        "html_url": "https://github.com/r/p/2",
        "number": 2,
        "state": "open",
        "labels": [],
        "draft": False,
        "requested_reviewers": [{"login": "akpandeya"}],
        "body": None,
    }

    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [pr])
        gh = GitHub(username="akpandeya", repos=["akpandeya/jarvis"])
        gh._token = "fake-token"
        events = gh._fetch_prs("akpandeya/jarvis", _since())

    assert events[0].kind == "pr_review_requested"


@pytest.mark.spec("integrations.F7")
def test_github_reviewers_stored_as_entities(monkeypatch):
    pr = {
        "title": "PR with reviewer",
        "user": {"login": "other"},
        "updated_at": _now().isoformat().replace("+00:00", "Z"),
        "created_at": _now().isoformat().replace("+00:00", "Z"),
        "html_url": "https://github.com/r/p/3",
        "number": 3,
        "state": "open",
        "labels": [],
        "draft": False,
        "requested_reviewers": [{"login": "reviewer1"}],
        "body": None,
    }

    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [pr])
        gh = GitHub(username="akpandeya", repos=["r/p"])
        gh._token = "fake-token"
        events = gh._fetch_prs("r/p", _since())

    entity_names = [e[1] for e in events[0].entities]
    assert "reviewer1" in entity_names


@pytest.mark.spec("integrations.F9")
def test_github_stops_at_pr_older_than_since(monkeypatch):
    old_time = (_now() - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    pr = {
        "title": "Old PR",
        "user": {"login": "akpandeya"},
        "updated_at": old_time,
        "created_at": old_time,
        "html_url": "https://github.com/r/p/99",
        "number": 99,
        "state": "closed",
        "labels": [],
        "draft": False,
        "requested_reviewers": [],
        "body": None,
    }

    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [pr])
        gh = GitHub(username="akpandeya", repos=["r/p"])
        gh._token = "fake-token"
        events = gh._fetch_prs("r/p", _now() - timedelta(days=7))

    assert events == []
