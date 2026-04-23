from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from rich.console import Console

from jarvis.config import JarvisConfig
from jarvis.db import get_db, link_event_entity, upsert_entity, upsert_event
from jarvis.integrations.base import RawEvent
from jarvis.integrations.gcal import GCal
from jarvis.integrations.git_local import GitLocal
from jarvis.integrations.github import GitHub
from jarvis.integrations.jira import Jira
from jarvis.integrations.kafka import Kafka

console = Console()


def _store_event(conn: sqlite3.Connection, raw: RawEvent) -> None:
    event_id = upsert_event(
        conn,
        source=raw.source,
        kind=raw.kind,
        title=raw.title,
        happened_at=raw.happened_at,
        body=raw.body,
        metadata=raw.metadata,
        url=raw.url,
        project=raw.project,
    )
    for entity_kind, entity_name, role in raw.entities:
        entity_id = upsert_entity(conn, kind=entity_kind, name=entity_name)
        link_event_entity(conn, event_id, entity_id, role)


def ingest_all(days: int = 7, source_filter: str | None = None) -> int:
    """Run all integrations and store events. Returns count of new events."""
    config = JarvisConfig.load()
    conn = get_db()
    since = datetime.now() - timedelta(days=days)
    total = 0

    integrations = []

    if config.git_local.repo_paths and source_filter in (None, "git_local"):
        integrations.append(GitLocal(repo_paths=config.git_local.repo_paths))

    if config.github.username and config.github.repos and source_filter in (None, "github"):
        integrations.append(GitHub(username=config.github.username, repos=config.github.repos))

    if config.jira.enabled and source_filter in (None, "jira"):
        integrations.append(Jira(project_keys=config.jira.project_keys or None))

    if config.gcal.credentials_path and source_filter in (None, "gcal"):
        integrations.append(
            GCal(
                calendar_id=config.gcal.calendar_id,
                credentials_path=config.gcal.credentials_path,
            )
        )

    if config.kafka.enabled and source_filter in (None, "kafka"):
        integrations.append(Kafka())

    for integration in integrations:
        name = integration.name
        if not integration.health_check():
            console.print(f"  [yellow]skip[/yellow] {name} (unavailable)")
            continue

        console.print(f"  [blue]pulling[/blue] {name}...")
        events = integration.fetch_since(since)
        for raw in events:
            _store_event(conn, raw)
        console.print(f"  [green]done[/green] {name}: {len(events)} events")
        total += len(events)

    # Run cross-source correlation
    from jarvis.correlator import correlate_events

    links = correlate_events(conn)
    if links:
        console.print(f"  [blue]correlated[/blue] {links} event-entity links")

    # Run entity resolution to merge duplicate people
    from jarvis.resolver import resolve_entities

    merges = resolve_entities(conn)
    if merges:
        console.print(f"  [blue]resolved[/blue] {merges} duplicate entities")

    # Collect computer-wide activity
    if source_filter in (None, "activity"):
        from jarvis.activity import collect_all

        activity_counts = collect_all(conn, since, config=config)
        activity_total = sum(activity_counts.values())
        if activity_total:
            console.print(
                f"  [green]activity[/green] {activity_total} new rows "
                f"({', '.join(f'{s}:{n}' for s, n in activity_counts.items() if n)})"
            )

    conn.close()
    return total
