"""Jira integration using the jira-cli (ankitpokhrel/jira-cli).

Shells out to the `jira` command which is already authenticated,
rather than requiring separate API token configuration.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime

from jarvis.integrations.base import RawEvent

# Read server URL from jira-cli config
_JIRA_CONFIG = None


def _load_jira_config() -> dict:
    global _JIRA_CONFIG
    if _JIRA_CONFIG is not None:
        return _JIRA_CONFIG

    from pathlib import Path

    config_path = Path.home() / ".config" / ".jira" / ".config.yml"
    if not config_path.exists():
        _JIRA_CONFIG = {}
        return _JIRA_CONFIG

    # Minimal YAML parsing — only need server, login, project.key
    result: dict = {}
    lines = config_path.read_text().splitlines()
    in_project = False
    for line in lines:
        if line.startswith("server:"):
            result["server"] = line.split(":", 1)[1].strip()
        elif line.startswith("login:"):
            result["login"] = line.split(":", 1)[1].strip()
        elif line.startswith("project:"):
            in_project = True
        elif in_project and line.startswith("    key:"):
            result["project_key"] = line.split(":", 1)[1].strip()
            in_project = False
        elif not line.startswith(" ") and not line.startswith("\t"):
            in_project = False

    _JIRA_CONFIG = result
    return _JIRA_CONFIG


class Jira:
    name = "jira"

    def __init__(self, project_keys: list[str] | None = None) -> None:
        config = _load_jira_config()
        self.server = config.get("server", "")
        self.project_keys = project_keys or []
        # Use the default project from jira-cli config if none specified
        if not self.project_keys and config.get("project_key"):
            self.project_keys = [config["project_key"]]

    def health_check(self) -> bool:
        if not shutil.which("jira"):
            return False
        try:
            result = subprocess.run(["jira", "me"], capture_output=True, text=True, timeout=10)
            return result.returncode == 0 and bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        since_str = since.strftime("%Y-%m-%d")

        for project_key in self.project_keys:
            events.extend(self._fetch_project_issues(project_key, since_str))

        return events

    def _fetch_project_issues(self, project_key: str, since_str: str) -> list[RawEvent]:
        events: list[RawEvent] = []

        jql = (
            f"project = {project_key} AND "
            f"(assignee = currentUser() OR reporter = currentUser()) AND "
            f'updated >= "{since_str}"'
        )

        try:
            result = subprocess.run(
                [
                    "jira",
                    "issue",
                    "list",
                    "--jql",
                    jql,
                    "--plain",
                    "--no-headers",
                    "--no-truncate",
                    "--columns",
                    "KEY,STATUS,SUMMARY,TYPE,UPDATED",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return events

        if result.returncode != 0:
            return events

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue

            # Output is tab-separated (sometimes with multiple tabs between columns)
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) < 3:
                continue

            key = parts[0]
            status = parts[1]
            summary = parts[2]
            issue_type = parts[3] if len(parts) > 3 else ""
            updated = parts[4] if len(parts) > 4 else ""

            # Parse the updated date — jira-cli may output various formats
            try:
                happened_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except (ValueError, IndexError):
                happened_at = datetime.now()

            url = f"{self.server}/browse/{key}" if self.server else None

            events.append(
                RawEvent(
                    source="jira",
                    kind="ticket_updated",
                    title=f"{key}: {summary}",
                    body=None,
                    happened_at=happened_at,
                    url=url,
                    project=project_key,
                    metadata={
                        "key": key,
                        "status": status,
                        "issue_type": issue_type,
                    },
                    entities=[],
                )
            )

        return events
