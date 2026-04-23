---
name: installer
description: One-command install experience — bootstrap script, interactive setup wizard, menu bar tray app, launchd boot agents, shiv artifact, and auto-update suggestions
component: jarvis/installer.py, jarvis/menubar.py, jarvis/updater.py, scripts/bootstrap.sh, scripts/build_shiv.sh, .github/workflows/release.yml
---

# Installer

## Behaviours

**F1** WHEN `scripts/bootstrap.sh` is run THEN it SHALL detect whether Python 3.11 or later is available; if not, it SHALL install pyenv and use it to install Python 3.11, and add pyenv initialisation to the user's shell profile.

**F2** WHEN `scripts/bootstrap.sh` completes the Python check THEN it SHALL download the latest `jarvis-*.pyz` artifact from the GitHub Releases page, place it at `~/.local/bin/jarvis.pyz`, create a symlink at `~/.local/bin/jarvis`, and invoke `jarvis install`.

**F3** WHEN `jarvis install` is run THEN it SHALL create `~/.jarvis/`, initialise the database, prompt the user for a GitHub personal access token and store it in the macOS Keychain, prompt for one or more `owner/repo` strings and write them to `~/.jarvis/config.toml`, and verify that the `claude` CLI is on PATH.

**F4** WHEN the user answers yes to the autostart prompt during `jarvis install` THEN it SHALL install three launchd agents: `com.jarvis.ingest` (every 15 min), `com.jarvis.pr_monitor` (every 2 h), and `com.jarvis.menubar` (persistent, KeepAlive).

**F5** WHEN `jarvis menubar` is run THEN a macOS menu bar icon labelled "J" SHALL appear with menu items: Open Dashboard, Run Ingest, Suggestions, and Quit Jarvis.

**F6** WHEN the menu bar icon is running THEN it SHALL refresh every 60 seconds and update the title to "J (n)" where n is the count of pending suggestions; when n is zero the title SHALL revert to "J".

**F7** WHEN the user clicks Open Dashboard in the menu bar THEN Jarvis SHALL start the FastAPI web server on port 8745 if it is not already running and open `http://localhost:8745` in the default browser.

**F8** WHEN the user clicks Run Ingest in the menu bar THEN `jarvis ingest --days 1` SHALL run as a background subprocess.

**F9** WHEN `jarvis/updater.py` is called THEN it SHALL fetch the latest release tag from the GitHub API and return True if the latest version is newer than the installed `jarvis.__version__`.

**F10** WHEN a newer version is available AND the local time is between 08:00 and 09:00 AND the update suggestion has not already fired today THEN the suggestion engine SHALL surface a suggestion with the new version number and the one-line install command as its action.

**F11** WHEN `scripts/build_shiv.sh` is run THEN it SHALL produce a compressed `dist/jarvis-<version>.pyz` executable that accepts `--help` without a full repo checkout.

**F12** WHEN a git tag matching `v*` is pushed THEN the GitHub Actions release workflow SHALL build the shiv artifact on `macos-latest` and attach it to a GitHub Release with auto-generated release notes.
