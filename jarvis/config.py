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


class GCalConfig(BaseModel):
    calendar_id: str = "primary"
    credentials_path: str = ""  # path to OAuth credentials JSON


class KafkaConfig(BaseModel):
    enabled: bool = True  # parses shell history for hfkcat/kcat commands


class FirefoxProfileConfig(BaseModel):
    path: str  # profile directory stem (the hash-prefixed folder name under Profiles/)
    label: str  # human label to store in metadata, e.g. "Work"


class FirefoxConfig(BaseModel):
    profiles: list[FirefoxProfileConfig] = Field(default_factory=list)


class ThunderbirdConfig(BaseModel):
    work_domains: list[str] = Field(default_factory=list)


class JarvisConfig(BaseModel):
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    git_local: GitLocalConfig = Field(default_factory=GitLocalConfig)
    jira: JiraConfig = Field(default_factory=JiraConfig)
    gcal: GCalConfig = Field(default_factory=GCalConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    firefox: FirefoxConfig = Field(default_factory=FirefoxConfig)
    thunderbird: ThunderbirdConfig = Field(default_factory=ThunderbirdConfig)

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

[gcal]
calendar_id = "primary"
credentials_path = ""

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

"""


def ensure_jarvis_home() -> None:
    """Create ~/.jarvis/ and default config if they don't exist."""
    JARVIS_HOME.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG_TOML)
