"""Entity resolution — merge the same person across sources.

Matches people by:
- Exact name match (case-insensitive)
- Email prefix == GitHub username (e.g., apandeya@corp.com ↔ apandeya)
- Known alias mappings from entities table
- Git author email matching Jira login

After resolution, all duplicate entity rows are merged into a single
canonical entity, and event_entities references are repointed.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from jarvis.db import get_db


def _normalize(name: str) -> str:
    """Lowercase, strip whitespace, remove dots for comparison."""
    return name.lower().strip().replace(".", "")


def _email_prefix(email: str) -> str:
    """Extract the local part of an email for fuzzy matching."""
    return email.split("@")[0].lower().strip()


def resolve_entities(conn: sqlite3.Connection | None = None) -> int:
    """Find and merge duplicate person entities.

    Returns the number of merges performed.
    """
    if conn is None:
        conn = get_db()

    # Load all person entities
    rows = conn.execute(
        "SELECT id, name, aliases, metadata FROM entities WHERE kind = 'person'"
    ).fetchall()

    if not rows:
        return 0

    # Build lookup structures
    entities: list[dict] = []
    for r in rows:
        aliases = json.loads(r["aliases"]) if r["aliases"] else []
        metadata = json.loads(r["metadata"]) if r["metadata"] else {}
        entities.append(
            {
                "id": r["id"],
                "name": r["name"],
                "aliases": aliases,
                "metadata": metadata,
            }
        )

    # Group by normalized name
    name_groups: dict[str, list[dict]] = defaultdict(list)
    for ent in entities:
        key = _normalize(ent["name"])
        name_groups[key].append(ent)
        # Also index by each alias
        for alias in ent["aliases"]:
            alias_key = _normalize(alias)
            name_groups[alias_key].append(ent)

    # Also build an email-prefix index from git metadata
    email_index: dict[str, list[dict]] = defaultdict(list)
    for ent in entities:
        email = ent["metadata"].get("email") or ""
        if email:
            email_index[_email_prefix(email)].append(ent)
        # GitHub usernames often match email prefixes
        name_lower = _normalize(ent["name"])
        email_index[name_lower].append(ent)

    # Union-Find to group equivalent entities
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Merge by exact normalized name
    for _key, group in name_groups.items():
        if len(group) > 1:
            base = group[0]["id"]
            for other in group[1:]:
                union(base, other["id"])

    # Merge by email prefix overlap
    for _prefix, group in email_index.items():
        if len(group) > 1:
            base = group[0]["id"]
            for other in group[1:]:
                union(base, other["id"])

    # Build final groups
    groups: dict[str, list[dict]] = defaultdict(list)
    for ent in entities:
        root = find(ent["id"])
        groups[root].append(ent)

    # Perform merges
    merges = 0
    for root_id, members in groups.items():
        if len(members) <= 1:
            continue

        # Pick the canonical entity: prefer the one with the longest name
        canonical = max(members, key=lambda e: len(e["name"]))
        canonical_id = canonical["id"]

        # Collect all names as aliases
        all_names = set()
        all_aliases = set()
        merged_metadata = {}
        for m in members:
            all_names.add(m["name"])
            all_aliases.update(m["aliases"])
            merged_metadata.update(m["metadata"])
        all_aliases.update(all_names)
        all_aliases.discard(canonical["name"])  # don't alias the canonical name

        # Update canonical entity
        conn.execute(
            "UPDATE entities SET aliases = ?, metadata = ? WHERE id = ?",
            (
                json.dumps(sorted(all_aliases)),
                json.dumps(merged_metadata) if merged_metadata else None,
                canonical_id,
            ),
        )

        # Repoint event_entities from duplicates to canonical
        for m in members:
            if m["id"] == canonical_id:
                continue
            # Move links — ignore conflicts (same event already linked to canonical)
            conn.execute(
                """UPDATE OR IGNORE event_entities
                   SET entity_id = ? WHERE entity_id = ?""",
                (canonical_id, m["id"]),
            )
            # Clean up any remaining orphaned links
            conn.execute("DELETE FROM event_entities WHERE entity_id = ?", (m["id"],))
            # Also repoint entity_links
            conn.execute(
                "UPDATE OR IGNORE entity_links SET from_entity = ? WHERE from_entity = ?",
                (canonical_id, m["id"]),
            )
            conn.execute(
                "UPDATE OR IGNORE entity_links SET to_entity = ? WHERE to_entity = ?",
                (canonical_id, m["id"]),
            )
            # Delete the duplicate entity
            conn.execute("DELETE FROM entities WHERE id = ?", (m["id"],))
            merges += 1

    conn.commit()
    return merges


def list_people(conn: sqlite3.Connection | None = None) -> list[dict]:
    """List all resolved person entities with their aliases."""
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        "SELECT id, name, aliases, metadata FROM entities WHERE kind = 'person' ORDER BY name"
    ).fetchall()

    people = []
    for r in rows:
        aliases = json.loads(r["aliases"]) if r["aliases"] else []
        # Count events linked to this entity
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM event_entities WHERE entity_id = ?", (r["id"],)
        ).fetchone()["cnt"]
        people.append(
            {
                "id": r["id"],
                "name": r["name"],
                "aliases": aliases,
                "event_count": count,
            }
        )

    return people
