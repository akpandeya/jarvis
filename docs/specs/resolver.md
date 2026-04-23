---
name: resolver
description: Entity resolution — deduplicates person entities across sources using Union-Find on name and email prefix matching
component: jarvis/resolver.py
---

# Resolver

## Behaviours

**F1** WHEN two person entities have the same normalised name (lowercase, stripped whitespace, dots removed) THEN `resolve_entities` SHALL merge them into one.

**F2** WHEN a person entity's email prefix matches another entity's normalised name or email prefix THEN `resolve_entities` SHALL merge them.

**F3** WHEN entities are merged THEN all `event_entities` links that pointed to duplicates SHALL be repointed to the canonical entity.

**F4** WHEN entities are merged THEN all `entity_links` rows referencing duplicates SHALL be repointed to the canonical entity.

**F5** WHEN entities are merged THEN duplicate entity rows SHALL be deleted from the `entities` table.

**F6** WHEN choosing which entity to keep as canonical THEN the entity with the longest name SHALL be preferred.

**F7** WHEN entities are merged THEN the names and aliases of all duplicates SHALL be collected into the canonical entity's `aliases` list; the canonical name itself SHALL not appear as an alias.

**F8** WHEN `resolve_entities` completes THEN it SHALL return the count of duplicate entities that were removed.

**F9** WHEN `list_people` is called THEN it SHALL return each person entity with their alias list and the count of events linked to them.
