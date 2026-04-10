from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class RawEvent:
    source: str
    kind: str
    title: str
    happened_at: datetime
    body: str | None = None
    metadata: dict | None = None
    url: str | None = None
    project: str | None = None
    entities: list[tuple[str, str, str]] = field(default_factory=list)
    # entities: list of (entity_kind, entity_name, role)


class Integration(Protocol):
    name: str

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        """Return events that occurred after `since`."""
        ...

    def health_check(self) -> bool:
        """Return True if the integration can connect."""
        ...
