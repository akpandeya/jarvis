from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent


class GitLocal:
    name = "git_local"

    def __init__(self, repo_paths: list[str]) -> None:
        self.repo_paths = [Path(p).expanduser() for p in repo_paths]

    def health_check(self) -> bool:
        return any(p.exists() and (p / ".git").exists() for p in self.repo_paths)

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        for repo_path in self.repo_paths:
            if not repo_path.exists() or not (repo_path / ".git").exists():
                continue
            events.extend(self._scan_repo(repo_path, since))
        return events

    def _scan_repo(self, repo_path: Path, since: datetime) -> list[RawEvent]:
        project = repo_path.name
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "log",
                    "--all",
                    f"--since={since_str}",
                    "--format=%H%x00%an%x00%ae%x00%aI%x00%s%x00%b%x1e",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        if result.returncode != 0:
            return []

        events: list[RawEvent] = []
        raw = result.stdout.strip()
        if not raw:
            return events

        for entry in raw.split("\x1e"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("\x00")
            if len(parts) < 5:
                continue

            sha, author_name, author_email, date_str, subject = parts[:5]
            body = parts[5].strip() if len(parts) > 5 else None

            events.append(
                RawEvent(
                    source="git_local",
                    kind="commit",
                    title=subject,
                    body=body or None,
                    happened_at=datetime.fromisoformat(date_str),
                    url=None,
                    project=project,
                    metadata={"sha": sha, "author_email": author_email},
                    entities=[("person", author_name, "author")],
                )
            )

        return events
