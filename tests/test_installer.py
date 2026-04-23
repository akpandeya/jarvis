"""Tests for jarvis/installer.py — keyed to docs/specs/installer.md."""

from unittest.mock import patch

import pytest


@pytest.mark.spec("installer.F4")
def test_install_launchd_agents_writes_three_plists(tmp_path, monkeypatch):
    # Redirect plist output to tmp_path
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir()
    monkeypatch.setattr(
        "jarvis.installer._write_plist",
        lambda label, args_xml, extra, log: (agents_dir / f"{label}.plist").write_text(
            f"{label}\n{args_xml}"
        ),
    )

    from jarvis.installer import install_launchd_agents

    install_launchd_agents(jarvis_bin="/usr/local/bin/jarvis")

    labels = {p.stem for p in agents_dir.glob("*.plist")}
    assert "com.jarvis.ingest" in labels
    assert "com.jarvis.pr_monitor" in labels
    assert "com.jarvis.menubar" in labels


@pytest.mark.spec("installer.F4")
def test_ingest_plist_has_interval():
    from jarvis.installer import _args_xml

    xml = _args_xml(["jarvis", "ingest", "--days", "1"])
    assert "<string>ingest</string>" in xml
    assert "<string>--days</string>" in xml


@pytest.mark.spec("installer.F10")
def test_update_suggestion_fires_in_window(db):
    import datetime

    fake_now = datetime.datetime(2026, 1, 1, 8, 30)
    with (
        patch("jarvis.suggestions.datetime") as mock_dt,
        patch("jarvis.updater.get_latest_version", return_value="0.2.0"),
        patch("jarvis.updater.update_available", return_value=True),
        patch("jarvis.__version__", "0.1.0", create=True),
    ):
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat = datetime.datetime.fromisoformat
        from jarvis.suggestions import _update_available

        result = _update_available(db)

    assert result is not None
    assert "0.2.0" in result.message
    assert result.rule_id == "update_available"


@pytest.mark.spec("installer.F10")
def test_update_suggestion_does_not_fire_outside_window(db):
    import datetime

    fake_now = datetime.datetime(2026, 1, 1, 14, 0)
    with patch("jarvis.suggestions.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat = datetime.datetime.fromisoformat
        from jarvis.suggestions import _update_available

        result = _update_available(db)
    assert result is None


def test_version_constant_is_set():
    import jarvis

    assert hasattr(jarvis, "__version__")
    assert jarvis.__version__ == "0.2.0"


def test_version_matches_pyproject(tmp_path):
    import jarvis

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    from pathlib import Path

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == jarvis.__version__
