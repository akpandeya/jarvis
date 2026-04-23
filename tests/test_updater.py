"""Tests for jarvis/updater.py — keyed to docs/specs/installer.md."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.spec("installer.F9")
def test_update_available_true_when_newer(monkeypatch):
    monkeypatch.setattr("jarvis.__version__", "0.1.0")
    with patch("jarvis.updater.get_latest_version", return_value="0.2.0"):
        from jarvis.updater import update_available

        assert update_available() is True


@pytest.mark.spec("installer.F9")
def test_update_available_false_when_same(monkeypatch):
    monkeypatch.setattr("jarvis.__version__", "0.2.0")
    with patch("jarvis.updater.get_latest_version", return_value="0.2.0"):
        from jarvis.updater import update_available

        assert update_available() is False


@pytest.mark.spec("installer.F9")
def test_update_available_false_when_older(monkeypatch):
    monkeypatch.setattr("jarvis.__version__", "0.3.0")
    with patch("jarvis.updater.get_latest_version", return_value="0.2.0"):
        from jarvis.updater import update_available

        assert update_available() is False


@pytest.mark.spec("installer.F9")
def test_update_available_false_on_network_error():
    with patch("jarvis.updater.get_latest_version", return_value=None):
        from jarvis.updater import update_available

        assert update_available() is False


def test_get_latest_version_returns_none_on_error():
    with patch("httpx.get", side_effect=Exception("timeout")):
        from jarvis.updater import get_latest_version

        assert get_latest_version() is None


def test_get_latest_version_strips_v_prefix():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"tag_name": "v0.5.1"}
    with patch("httpx.get", return_value=mock_resp):
        from jarvis.updater import get_latest_version

        assert get_latest_version() == "0.5.1"
