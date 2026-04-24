from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic import BaseModel, Field

JARVIS_HOME = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
CONFIG_PATH = JARVIS_HOME / "config.toml"
DB_PATH = JARVIS_HOME / "jarvis.db"


class GitHubConfig(BaseModel):
    username: str = ""
    repos: list[str] = Field(default_factory=list)


class GitLocalConfig(BaseModel):
    repo_paths: list[str] = Field(default_factory=list)


class JiraConfig(BaseModel):
    enabled: bool = True  # uses jira-cli, no extra auth needed
    project_keys: list[str] = Field(default_factory=list)  # empty = use jira-cli default project


class GCalAccountConfig(BaseModel):
    name: str  # human label, e.g. "Work" or "Personal"
    credentials_path: str  # path to OAuth client credentials JSON
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])


class GCalConfig(BaseModel):
    accounts: list[GCalAccountConfig] = Field(default_factory=list)


class KafkaConfig(BaseModel):
    enabled: bool = True  # parses shell history for hfkcat/kcat commands


class FirefoxProfileConfig(BaseModel):
    path: str  # profile directory stem (the hash-prefixed folder name under Profiles/)
    label: str  # human label to store in metadata, e.g. "Work"


class FirefoxConfig(BaseModel):
    profiles: list[FirefoxProfileConfig] = Field(default_factory=list)


class ThunderbirdConfig(BaseModel):
    work_domains: list[str] = Field(default_factory=list)


class PrMonitorConfig(BaseModel):
    account_keys: list[str] = Field(default_factory=lambda: ["github_token"])
    staging_patterns: list[str] = Field(default_factory=lambda: ["staging", "stg", "stage"])
    max_files: int = 10
    max_lines: int = 500
    review_model: str = "claude-opus-4-7"


class JarvisConfig(BaseModel):
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    git_local: GitLocalConfig = Field(default_factory=GitLocalConfig)
    jira: JiraConfig = Field(default_factory=JiraConfig)
    gcal: GCalConfig = Field(default_factory=GCalConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    firefox: FirefoxConfig = Field(default_factory=FirefoxConfig)
    thunderbird: ThunderbirdConfig = Field(default_factory=ThunderbirdConfig)
    pr_monitor: PrMonitorConfig = Field(default_factory=PrMonitorConfig)

    @classmethod
    def load(cls) -> JarvisConfig:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                data = tomllib.load(f)
            return cls.model_validate(data)
        return cls()


DEFAULT_CONFIG_TOML = """\
# Jarvis configuration
# Credentials are stored in the macOS Keychain via `keyring`, not here.

[github]
username = ""
repos = [
    # "owner/repo",
]

[git_local]
repo_paths = [
    # "~/code/my-project",
]

[jira]
enabled = true  # uses your existing jira-cli auth
project_keys = [
    # "TGH",  # leave empty to use jira-cli default project
]

# Google Calendar — add one [[gcal.accounts]] block per Google account
# [[gcal.accounts]]
# name = "Work"
# credentials_path = "~/.jarvis/gcal_work_creds.json"
# calendar_ids = ["primary"]   # or add specific calendar IDs
#
# [[gcal.accounts]]
# name = "Personal"
# credentials_path = "~/.jarvis/gcal_personal_creds.json"
# calendar_ids = ["primary"]

[kafka]
enabled = true  # parses shell history for hfkcat/kcat commands

[firefox]
# Optional: label Firefox profiles. path = profile directory stem.
# [[firefox.profiles]]
# path = "xxxxxxxx.default-release"
# label = "Work"

[thunderbird]
# Set your work email domains so Jarvis can label emails correctly.
# work_domains = ["yourcompany.com"]

[pr_monitor]
# GitHub keychain key names (one per account). Each must hold a token via `jarvis setup`.
account_keys = ["github_token"]
# Environment name substrings that count as staging.
staging_patterns = ["staging", "stg", "stage"]
# Oversized PR thresholds.
max_files = 10
max_lines = 500
# Model used for PR review chat (any Claude model ID).
review_model = "claude-opus-4-7"

"""


def ensure_jarvis_home() -> None:
    """Create ~/.jarvis/ and default config if they don't exist."""
    JARVIS_HOME.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG_TOML)
