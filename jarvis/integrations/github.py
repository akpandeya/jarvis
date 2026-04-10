from __future__ import annotations

from datetime import datetime

import httpx
import keyring

from jarvis.integrations.base import RawEvent

API_BASE = "https://api.github.com"


class GitHub:
    name = "github"

    def __init__(self, username: str, repos: list[str]) -> None:
        self.username = username
        self.repos = repos
        self._token: str | None = None

    def _get_token(self) -> str | None:
        if self._token is None:
            self._token = keyring.get_password("jarvis", "github_token")
        return self._token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def health_check(self) -> bool:
        token = self._get_token()
        if not token:
            return False
        try:
            resp = httpx.get(f"{API_BASE}/user", headers=self._headers(), timeout=10)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        for repo in self.repos:
            events.extend(self._fetch_prs(repo, since))
            events.extend(self._fetch_commits(repo, since))
        return events

    def _fetch_prs(self, repo: str, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        try:
            resp = httpx.get(
                f"{API_BASE}/repos/{repo}/pulls",
                headers=self._headers(),
                params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 30},
                timeout=15,
            )
            if resp.status_code != 200:
                return events
        except httpx.RequestError:
            return events

        for pr in resp.json():
            updated = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
            if updated < since.replace(tzinfo=updated.tzinfo):
                break

            user = pr["user"]["login"]
            is_mine = user.lower() == self.username.lower()
            kind = "pr_opened" if is_mine else "pr_review_requested"

            entities: list[tuple[str, str, str]] = [("person", user, "author")]
            for reviewer in (pr.get("requested_reviewers") or []):
                entities.append(("person", reviewer["login"], "reviewer"))

            events.append(
                RawEvent(
                    source="github",
                    kind=kind,
                    title=pr["title"],
                    body=pr.get("body"),
                    happened_at=datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00")),
                    url=pr["html_url"],
                    project=repo.split("/")[-1],
                    metadata={
                        "number": pr["number"],
                        "state": pr["state"],
                        "labels": [l["name"] for l in pr.get("labels", [])],
                        "draft": pr.get("draft", False),
                    },
                    entities=entities,
                )
            )
        return events

    def _fetch_commits(self, repo: str, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        try:
            resp = httpx.get(
                f"{API_BASE}/repos/{repo}/commits",
                headers=self._headers(),
                params={"author": self.username, "since": since.isoformat(), "per_page": 30},
                timeout=15,
            )
            if resp.status_code != 200:
                return events
        except httpx.RequestError:
            return events

        for commit in resp.json():
            c = commit["commit"]
            date_str = c["author"]["date"]
            author_name = c["author"]["name"]

            events.append(
                RawEvent(
                    source="github",
                    kind="commit",
                    title=c["message"].split("\n")[0],
                    body=c["message"] if "\n" in c["message"] else None,
                    happened_at=datetime.fromisoformat(date_str.replace("Z", "+00:00")),
                    url=commit["html_url"],
                    project=repo.split("/")[-1],
                    metadata={"sha": commit["sha"]},
                    entities=[("person", author_name, "author")],
                )
            )
        return events
