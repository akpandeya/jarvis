"""Jira board subscriptions — ingests active-sprint issues.

Companion to `jarvis/integrations/jira.py`. The vanilla `Jira` integration
pulls tickets where the user is assignee or reporter and were recently
updated ("recent"). This one pulls every ticket in the active sprint of each
subscribed board, regardless of who touched it, so the briefing can surface
unassigned tickets and team-wide context.

One ticket can qualify for both pipelines; it lands as a single entity with
`source_tags` = `["recent", "board:<id>"]` thanks to `merge_metadata=True`
upserts.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime

from jarvis.db import get_db, list_jira_board_subs
from jarvis.integrations.base import RawEvent
from jarvis.integrations.jira import _load_jira_config


class JiraBoards:
    name = "jira_boards"

    def __init__(self) -> None:
        config = _load_jira_config()
        self.server = config.get("server", "")
        # Cache DB subs for the duration of fetch_since.
        self._subs: list[dict] = []

    def health_check(self) -> bool:
        if not shutil.which("jira"):
            return False
        try:
            result = subprocess.run(["jira", "me"], capture_output=True, text=True, timeout=10)
            if not (result.returncode == 0 and result.stdout.strip()):
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        conn = get_db()
        self._subs = list_jira_board_subs(conn)
        conn.close()
        return bool(self._subs)

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        for sub in self._subs:
            events.extend(self._fetch_board(sub))
        return events

    def _fetch_board(self, sub: dict) -> list[RawEvent]:
        project_key: str = sub["project_key"]
        board_id: int = sub["board_id"]
        nickname: str = sub["nickname"]
        tag = f"board:{board_id}"
        sprint_name = self._active_sprint_name(project_key)

        events: list[RawEvent] = []
        # Three disjoint buckets: mine, unassigned, others. Running them as
        # separate JQLs removes the need to parse assignee names out of the
        # fixed-width tabbed output, which jira-cli formats with a variable
        # number of padding tabs per row.
        buckets: list[tuple[str, str]] = [
            ("mine", "assignee = currentUser()"),
            ("unassigned", "assignee is EMPTY"),
            (
                "others",
                "assignee != currentUser() AND assignee is not EMPTY",
            ),
        ]
        for bucket, predicate in buckets:
            jql = f"sprint in openSprints() AND project = {project_key} AND {predicate}"
            result = subprocess.run(
                [
                    "jira",
                    "issue",
                    "list",
                    "--project",
                    project_key,
                    "--jql",
                    jql,
                    "--plain",
                    "--no-headers",
                    "--no-truncate",
                    "--columns",
                    "KEY,STATUS,ASSIGNEE,TYPE,SUMMARY,PRIORITY",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                continue

            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                # jira-cli fixed-width tabbed output: consecutive tabs pad the
                # columns. Collapse to non-empty tokens and read by order.
                toks = [p.strip() for p in line.split("\t") if p.strip()]
                if not toks:
                    continue
                key = toks[0]
                status = toks[1] if len(toks) > 1 else ""
                # The assignee column is absent on unassigned rows, so the
                # TYPE token slides left. Use the bucket to decide.
                if bucket == "unassigned":
                    assignee = ""
                    issue_type = toks[2] if len(toks) > 2 else ""
                    summary = toks[3] if len(toks) > 3 else ""
                    priority = toks[4] if len(toks) > 4 else ""
                else:
                    assignee = toks[2] if len(toks) > 2 else ""
                    issue_type = toks[3] if len(toks) > 3 else ""
                    summary = toks[4] if len(toks) > 4 else ""
                    priority = toks[5] if len(toks) > 5 else ""

                url = f"{self.server}/browse/{key}" if self.server else None
                events.append(
                    RawEvent(
                        source="jira",
                        kind="sprint_issue",
                        title=f"{key}: {summary}",
                        happened_at=datetime.now(),
                        url=url,
                        project=project_key,
                        metadata={
                            "key": key,
                            "status": status,
                            "issue_type": issue_type,
                            "assignee": assignee,
                            "priority": priority,
                            "board_id": board_id,
                            "board_nickname": nickname,
                            "sprint_name": sprint_name,
                            "bucket": bucket,
                        },
                        entities=[
                            (
                                "jira_issue",
                                key,
                                "subject",
                                {
                                    "status": status,
                                    "issue_type": issue_type,
                                    "summary": summary,
                                    "assignee": assignee,
                                    "priority": priority,
                                    "url": url,
                                    "board_id": board_id,
                                    "board_nickname": nickname,
                                    "sprint_name": sprint_name,
                                    "bucket": bucket,
                                    "source_tags": [tag],
                                },
                            )
                        ],
                    )
                )
        return events

    def _active_sprint_name(self, project_key: str) -> str:
        """Return the name of the current active sprint in this project, or ''."""
        try:
            r = subprocess.run(
                [
                    "jira",
                    "sprint",
                    "list",
                    "--project",
                    project_key,
                    "--state",
                    "active",
                    "--plain",
                    "--no-headers",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""
        if r.returncode != 0:
            return ""
        # Columns: id, name, start, end. Take the first (most recent) row.
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) >= 2:
                return parts[1]
        return ""
