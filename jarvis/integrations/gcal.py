from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent

TOKEN_PATH = Path.home() / ".jarvis" / "gcal_token.json"


class GCal:
    name = "gcal"

    def __init__(self, calendar_id: str = "primary", credentials_path: str = "") -> None:
        self.calendar_id = calendar_id
        self.credentials_path = credentials_path

    def _get_service(self):
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds = None

        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
            else:
                if not self.credentials_path or not Path(self.credentials_path).exists():
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, scopes)
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.write_text(creds.to_json())

        return build("calendar", "v3", credentials=creds)

    def health_check(self) -> bool:
        try:
            service = self._get_service()
            return service is not None
        except Exception:
            return False

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []

        try:
            service = self._get_service()
            if service is None:
                return events
        except Exception:
            return events

        time_min = since.isoformat() + "Z" if since.tzinfo is None else since.isoformat()

        try:
            result = (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    maxResults=50,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception:
            return events

        for item in result.get("items", []):
            start = item.get("start", {})
            start_str = start.get("dateTime") or start.get("date")
            if not start_str:
                continue

            try:
                happened_at = datetime.fromisoformat(start_str)
            except ValueError:
                # date-only events like "2026-04-10"
                happened_at = datetime.fromisoformat(start_str + "T00:00:00")

            attendees = item.get("attendees", [])
            entities: list[tuple[str, str, str]] = []
            for a in attendees:
                name = a.get("displayName") or a.get("email", "")
                if name:
                    entities.append(("person", name, "attendee"))

            organizer = item.get("organizer", {})
            org_name = organizer.get("displayName") or organizer.get("email", "")
            if org_name:
                entities.append(("person", org_name, "organizer"))

            events.append(
                RawEvent(
                    source="gcal",
                    kind="meeting",
                    title=item.get("summary", "(no title)"),
                    body=item.get("description"),
                    happened_at=happened_at,
                    url=item.get("htmlLink"),
                    project=None,
                    metadata={
                        "location": item.get("location"),
                        "status": item.get("status"),
                        "attendee_count": len(attendees),
                        "recurring": bool(item.get("recurringEventId")),
                    },
                    entities=entities,
                )
            )

        return events
