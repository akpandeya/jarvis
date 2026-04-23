---
name: config
description: Reads ~/.jarvis/config.toml into typed config models; manages the Jarvis home directory and default config file
component: jarvis/config.py
---

# Config

## Behaviours

**F1** WHEN `config.toml` does not exist THEN `JarvisConfig.load` SHALL return a config object with all fields at their defaults.

**F2** WHEN `config.toml` exists THEN `JarvisConfig.load` SHALL parse it and validate all fields through Pydantic.

**F3** WHEN the `JARVIS_HOME` environment variable is set THEN all paths (config, DB) SHALL use that directory instead of `~/.jarvis`.

**F4** WHEN `ensure_jarvis_home` is called and the directory does not exist THEN it SHALL create `~/.jarvis` and write the default `config.toml`.

**F5** WHEN `ensure_jarvis_home` is called and `config.toml` already exists THEN it SHALL not overwrite it.

**F6** WHEN `thunderbird.work_domains` is empty THEN all emails SHALL be treated as personal by the activity collector.

**F7** WHEN a `[[firefox.profiles]]` entry matches a profile directory stem THEN that label SHALL override any other label source for that profile.

**F8** WHEN no `[[firefox.profiles]]` entry matches a profile THEN the label SHALL be read from `prefs.js`; if that also fails the directory stem SHALL be used.

**F9** WHEN credentials (e.g. GitHub token) are needed THEN they SHALL be read from the macOS Keychain via `keyring`, not from `config.toml`.
