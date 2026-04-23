"""Tests for jarvis/config.py — keyed to docs/specs/config.md."""

import pytest

from jarvis.config import JarvisConfig, ensure_jarvis_home


@pytest.mark.spec("config.F1")
def test_load_returns_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", tmp_path / "config.toml")
    cfg = JarvisConfig.load()
    assert cfg.github.username == ""
    assert cfg.thunderbird.work_domains == []
    assert cfg.firefox.profiles == []


@pytest.mark.spec("config.F2")
def test_load_parses_toml(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[github]\nusername = "akpandeya"\nrepos = ["akpandeya/jarvis"]\n')
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", config_path)
    cfg = JarvisConfig.load()
    assert cfg.github.username == "akpandeya"
    assert cfg.github.repos == ["akpandeya/jarvis"]


@pytest.mark.spec("config.F3")
def test_jarvis_home_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    import importlib

    import jarvis.config as cfg_mod

    importlib.reload(cfg_mod)
    assert str(tmp_path) in str(cfg_mod.CONFIG_PATH)
    importlib.reload(cfg_mod)  # restore


@pytest.mark.spec("config.F4")
def test_ensure_jarvis_home_creates_dir_and_config(tmp_path, monkeypatch):
    home = tmp_path / ".jarvis"
    monkeypatch.setattr("jarvis.config.JARVIS_HOME", home)
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", home / "config.toml")
    ensure_jarvis_home()
    assert home.exists()
    assert (home / "config.toml").exists()


@pytest.mark.spec("config.F5")
def test_ensure_jarvis_home_does_not_overwrite(tmp_path, monkeypatch):
    home = tmp_path / ".jarvis"
    home.mkdir()
    config = home / "config.toml"
    config.write_text("# my custom config\n")
    monkeypatch.setattr("jarvis.config.JARVIS_HOME", home)
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", config)
    ensure_jarvis_home()
    assert config.read_text() == "# my custom config\n"


@pytest.mark.spec("config.F6")
def test_empty_work_domains_default(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", tmp_path / "config.toml")
    cfg = JarvisConfig.load()
    assert cfg.thunderbird.work_domains == []


@pytest.mark.spec("config.F7")
def test_firefox_profile_label_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[[firefox.profiles]]\npath = "abc123.default"\nlabel = "Work"\n')
    monkeypatch.setattr("jarvis.config.CONFIG_PATH", config_path)
    cfg = JarvisConfig.load()
    assert cfg.firefox.profiles[0].label == "Work"
    assert cfg.firefox.profiles[0].path == "abc123.default"
