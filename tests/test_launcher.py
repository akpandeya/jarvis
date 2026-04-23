"""Tests for jarvis/launcher.py."""

import os
from unittest.mock import patch

import pytest

from jarvis.launcher import _already_running, _write_pid, clear_pid


@pytest.fixture(autouse=True)
def isolated_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "jarvis.pid"
    monkeypatch.setattr("jarvis.launcher._PID_FILE", pid_file)
    yield pid_file


def test_not_running_when_no_pid_file(isolated_pid):
    assert _already_running() is False


def test_not_running_when_pid_file_stale(isolated_pid):
    # Write a PID that definitely does not exist
    isolated_pid.write_text("999999999")
    assert _already_running() is False
    assert not isolated_pid.exists()  # stale file removed


def test_running_when_pid_is_current_process(isolated_pid):
    _write_pid(os.getpid())
    assert _already_running() is True


def test_clear_pid_removes_file(isolated_pid):
    _write_pid(os.getpid())
    assert isolated_pid.exists()
    clear_pid()
    assert not isolated_pid.exists()


def test_clear_pid_is_idempotent(isolated_pid):
    clear_pid()  # no file — should not raise
    clear_pid()


def test_launch_prints_already_running(isolated_pid, capsys):
    _write_pid(os.getpid())
    from jarvis.launcher import launch

    with patch("jarvis.launcher._start_daemon") as mock_start:
        launch()
        mock_start.assert_not_called()


def test_launch_starts_daemons_when_not_running(isolated_pid):
    from jarvis.launcher import launch

    with (
        patch("jarvis.launcher._start_daemon") as mock_start,
        patch("jarvis.launcher._find_jarvis", return_value="/usr/local/bin/jarvis"),
    ):
        mock_start.return_value.pid = 12345
        launch()
        assert mock_start.call_count == 2
        cmds = [call.args[0] for call in mock_start.call_args_list]
        assert any("menubar" in c for c in cmds)
        assert any("web" in c for c in cmds)
