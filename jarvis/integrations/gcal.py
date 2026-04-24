from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _token_path(account_name: str) -> Path:
    slug = account_name.lower().replace(" ", "_")
    return Path.home() / ".jarvis" / f"gcal_token_{slug}.json"


def _get_service(account_name: str, credentials_path: str):
    """Return an authenticated Google Calendar service, or None if not possible."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_file = _token_path(account_name)
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        else:
            if not credentials_path or not Path(credentials_path).exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def authenticate(account_name: str, credentials_path: str) -> bool:
    """Run the OAuth flow interactively. Returns True on success."""
    try:
        svc = _get_service(account_name, credentials_path)
        return svc is not None
    except Exception:
        return False


def list_calendars(account_name: str, credentials_path: str) -> list[dict]:
    """Return all calendars for an account as [{id, name, primary}]."""
    svc = _get_service(account_name, credentials_path)
    if svc is None:
        return []
    result = svc.calendarList().list().execute()
    return [
        {
            "id": c["id"],
            "name": c.get("summary", ""),
            "primary": c.get("primary", False),
        }
        for c in result.get("items", [])
    ]


class GCal:
    name = "gcal"

    def __init__(
        self,
        account_name: str,
        credentials_path: str,
        calendar_ids: list[str] | None = None,
    ) -> None:
        self.account_name = account_name
        self.credentials_path = credentials_path
        self.calendar_ids = calendar_ids or ["primary"]

    def health_check(self) -> bool:
        try:
            return _get_service(self.account_name, self.credentials_path) is not None
        except Exception:
            return False

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []

        try:
            service = _get_service(self.account_name, self.credentials_path)
            if service is None:
                return events
        except Exception:
            return events

        time_min = since.isoformat() + "Z" if since.tzinfo is None else since.isoformat()

        for cal_id in self.calendar_ids:
            try:
                result = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min,
                        maxResults=50,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
            except Exception:
                continue

            for item in result.get("items", []):
                start = item.get("start", {})
                start_str = start.get("dateTime") or start.get("date")
                if not start_str:
                    continue

                try:
                    happened_at = datetime.fromisoformat(start_str)
                except ValueError:
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
                            "account": self.account_name,
                            "calendar_id": cal_id,
                        },
                        entities=entities,
                    )
                )

        return events
