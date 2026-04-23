"""Tests for jarvis/brain.py — keyed to docs/specs/brain.md."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from jarvis.brain import _call_claude, _format_events, answer_query, summarize_events
from jarvis.models import Event


def _make_event(**kwargs):
    defaults = dict(
        id="01ABC",
        source="github",
        kind="commit",
        title="Fix bug",
        happened_at=datetime.now(UTC),
        body=None,
        metadata=None,
        url=None,
        project=None,
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# F2: raises when claude CLI missing
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F2")
def test_call_claude_raises_when_cli_missing(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="claude CLI not found"):
        _call_claude("system", "user")


# ---------------------------------------------------------------------------
# F3: raises on non-zero exit
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F3")
def test_call_claude_raises_on_nonzero_exit(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/claude")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="timeout")
        with pytest.raises(RuntimeError, match="claude CLI failed"):
            _call_claude("system", "user")


# ---------------------------------------------------------------------------
# F4: empty events → placeholder string
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F4")
def test_format_events_empty_returns_placeholder():
    result = _format_events([])
    assert "No events" in result
    assert len(result) > 0


# ---------------------------------------------------------------------------
# F5: URL included in output
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F5")
def test_format_events_includes_url():
    e = _make_event(url="https://github.com/pr/1")
    result = _format_events([e])
    assert "https://github.com/pr/1" in result


# ---------------------------------------------------------------------------
# F6: short body included, truncated at 300 chars
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F6")
def test_format_events_includes_short_body():
    e = _make_event(body="Short description")
    result = _format_events([e])
    assert "Short description" in result


@pytest.mark.spec("brain.F6")
def test_format_events_omits_long_body():
    e = _make_event(body="x" * 600)
    result = _format_events([e])
    # body over 500 chars is not included
    assert "x" * 300 not in result


# ---------------------------------------------------------------------------
# F7: sha in metadata → short sha
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F7")
def test_format_events_includes_short_sha():
    e = _make_event(metadata={"sha": "abcdef1234567890"})
    result = _format_events([e])
    assert "sha:abcdef12" in result


# ---------------------------------------------------------------------------
# F8: number in metadata → #N
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F8")
def test_format_events_includes_pr_number():
    e = _make_event(metadata={"number": 42})
    result = _format_events([e])
    assert "#42" in result


# ---------------------------------------------------------------------------
# F9 & F10: standup prompt period headings
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F9")
def test_summarize_events_standup_single_day(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/claude")
    captured = {}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="standup output")

        def capture(*args, **kwargs):
            captured["args"] = args
            return MagicMock(returncode=0, stdout="standup output")

        mock_run.side_effect = capture
        summarize_events([_make_event()], prompt_type="standup", days=1)

    cli_args = captured["args"][0]
    system_prompt = cli_args[cli_args.index("--append-system-prompt") + 1]
    assert "Yesterday" in system_prompt


@pytest.mark.spec("brain.F10")
def test_summarize_events_standup_multi_day(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/claude")
    captured = {}
    with patch("subprocess.run") as mock_run:

        def capture(*args, **kwargs):
            captured["args"] = args
            return MagicMock(returncode=0, stdout="standup output")

        mock_run.side_effect = capture
        summarize_events([_make_event()], prompt_type="standup", days=3)

    cli_args = captured["args"][0]
    system_prompt = cli_args[cli_args.index("--append-system-prompt") + 1]
    assert "Last 3 days" in system_prompt


# ---------------------------------------------------------------------------
# F11: answer_query includes events + question in user message
# ---------------------------------------------------------------------------


@pytest.mark.spec("brain.F11")
def test_answer_query_includes_events_and_question(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/claude")
    captured = {}
    with patch("subprocess.run") as mock_run:

        def capture(*args, **kwargs):
            captured["input"] = kwargs.get("input", "")
            return MagicMock(returncode=0, stdout="answer")

        mock_run.side_effect = capture
        answer_query("What did I work on?", [_make_event(title="Deployed service")])

    assert "Deployed service" in captured["input"]
    assert "What did I work on?" in captured["input"]
