from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    id: str
    source: str
    kind: str
    title: str
    happened_at: datetime
    body: str | None = None
    metadata: dict | None = None
    url: str | None = None
    ingested_at: datetime | None = None
    project: str | None = None

    def metadata_json(self) -> str | None:
        if self.metadata is None:
            return None
        return json.dumps(self.metadata)

    @classmethod
    def from_row(cls, row: dict) -> Event:
        meta = row.get("metadata")
        return cls(
            id=row["id"],
            source=row["source"],
            kind=row["kind"],
            title=row["title"],
            body=row.get("body"),
            metadata=json.loads(meta) if meta else None,
            url=row.get("url"),
            happened_at=datetime.fromisoformat(row["happened_at"]),
            ingested_at=(
                datetime.fromisoformat(row["ingested_at"]) if row.get("ingested_at") else None
            ),
            project=row.get("project"),
        )


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict | None = None
