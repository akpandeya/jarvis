"""Work pattern detection — analyze habits from event data.

Detects:
- Time-of-day distribution (when you're most active)
- Day-of-week distribution
- Collaboration frequency (who you work with most)
- Context-switching rate (how often you switch projects)
- Source distribution (where work happens)
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from jarvis.db import get_db, query_events


def time_of_day_distribution(
    conn: sqlite3.Connection | None = None, days: int = 30
) -> dict[str, int]:
    """Count events by hour of day. Returns {hour_label: count}."""
    if conn is None:
        conn = get_db()
    events = query_events(conn, days=days, limit=2000)

    hours: Counter[int] = Counter()
    for e in events:
        hours[e.happened_at.hour] += 1

    return {f"{h:02d}:00": hours.get(h, 0) for h in range(24)}


def day_of_week_distribution(
    conn: sqlite3.Connection | None = None, days: int = 30
) -> dict[str, int]:
    """Count events by day of week."""
    if conn is None:
        conn = get_db()
    events = query_events(conn, days=days, limit=2000)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_counter: Counter[int] = Counter()
    for e in events:
        days_counter[e.happened_at.weekday()] += 1

    return {day_names[i]: days_counter.get(i, 0) for i in range(7)}


def collaboration_frequency(
    conn: sqlite3.Connection | None = None, days: int = 30, top_n: int = 15
) -> list[dict]:
    """Find who you collaborate with most, based on shared entities."""
    if conn is None:
        conn = get_db()

    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT ent.name, COUNT(*) as cnt
           FROM event_entities ee
           JOIN entities ent ON ee.entity_id = ent.id
           JOIN events ev ON ee.event_id = ev.id
           WHERE ent.kind = 'person' AND ev.happened_at >= ?
           GROUP BY ent.id
           ORDER BY cnt DESC
           LIMIT ?""",
        (since, top_n),
    ).fetchall()

    return [{"name": r["name"], "events": r["cnt"]} for r in rows]


def context_switches(conn: sqlite3.Connection | None = None, days: int = 7) -> dict:
    """Measure context-switching: how often you jump between projects in a day."""
    if conn is None:
        conn = get_db()
    events = query_events(conn, days=days, limit=2000)

    # Group events by date
    by_date: dict[str, list] = defaultdict(list)
    for e in events:
        date_key = e.happened_at.strftime("%Y-%m-%d")
        by_date[date_key].append(e)

    daily_switches = {}
    for date_key, day_events in sorted(by_date.items()):
        # Sort by time
        day_events.sort(key=lambda e: e.happened_at)
        switches = 0
        prev_project = None
        for e in day_events:
            proj = e.project or e.source
            if prev_project and proj != prev_project:
                switches += 1
            prev_project = proj
        daily_switches[date_key] = switches

    total_switches = sum(daily_switches.values())
    num_days = len(daily_switches) or 1

    return {
        "daily": daily_switches,
        "avg_per_day": round(total_switches / num_days, 1),
        "total": total_switches,
    }


def source_distribution(conn: sqlite3.Connection | None = None, days: int = 30) -> dict[str, int]:
    """Count events by source."""
    if conn is None:
        conn = get_db()

    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT source, COUNT(*) as cnt FROM events
           WHERE happened_at >= ?
           GROUP BY source ORDER BY cnt DESC""",
        (since,),
    ).fetchall()

    return {r["source"]: r["cnt"] for r in rows}


def project_distribution(conn: sqlite3.Connection | None = None, days: int = 30) -> dict[str, int]:
    """Count events by project."""
    if conn is None:
        conn = get_db()

    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT COALESCE(project, '(none)') as proj, COUNT(*) as cnt FROM events
           WHERE happened_at >= ?
           GROUP BY project ORDER BY cnt DESC""",
        (since,),
    ).fetchall()

    return {r["proj"]: r["cnt"] for r in rows}


def generate_insights(conn: sqlite3.Connection | None = None, days: int = 30) -> str:
    """Generate a human-readable insights summary."""
    if conn is None:
        conn = get_db()

    lines = []

    # Time distribution
    tod = time_of_day_distribution(conn, days)
    if tod:
        peak_hour = max(tod, key=tod.get)  # type: ignore[arg-type]
        lines.append(f"**Peak activity hour:** {peak_hour} ({tod[peak_hour]} events)")

    # Day distribution
    dow = day_of_week_distribution(conn, days)
    if dow:
        peak_day = max(dow, key=dow.get)  # type: ignore[arg-type]
        weekend = dow.get("Saturday", 0) + dow.get("Sunday", 0)
        lines.append(f"**Most active day:** {peak_day} ({dow[peak_day]} events)")
        if weekend > 0:
            lines.append(f"**Weekend activity:** {weekend} events")

    # Source distribution
    sources = source_distribution(conn, days)
    if sources:
        parts = [f"{s}: {c}" for s, c in sources.items()]
        lines.append(f"**Sources:** {', '.join(parts)}")

    # Project distribution
    projects = project_distribution(conn, days)
    if projects:
        parts = [f"{p}: {c}" for p, c in list(projects.items())[:5]]
        lines.append(f"**Top projects:** {', '.join(parts)}")

    # Context switching
    ctx = context_switches(conn, min(days, 7))
    lines.append(f"**Avg context switches/day:** {ctx['avg_per_day']}")

    # Collaboration
    collabs = collaboration_frequency(conn, days, top_n=5)
    if collabs:
        names = [f"{c['name']} ({c['events']})" for c in collabs]
        lines.append(f"**Top collaborators:** {', '.join(names)}")

    return "\n".join(lines) if lines else "Not enough data for pattern analysis."
