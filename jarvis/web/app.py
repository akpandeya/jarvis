from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from jarvis.db import event_count, get_db, list_sessions, query_events, search_events

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Jarvis Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
def timeline(
    request: Request,
    source: str | None = Query(None),
    project: str | None = Query(None),
    days: int = Query(14),
    page: int = Query(1),
):
    per_page = 30
    conn = get_db()
    events = query_events(conn, source=source, project=project, days=days, limit=per_page * page)
    page_events = events[(page - 1) * per_page :]
    total = event_count(conn)

    sources = conn.execute("SELECT DISTINCT source FROM events ORDER BY source").fetchall()
    projects = conn.execute(
        "SELECT DISTINCT project FROM events WHERE project IS NOT NULL ORDER BY project"
    ).fetchall()
    conn.close()

    ctx = {
        "events": page_events,
        "total": total,
        "source": source,
        "project": project,
        "days": days,
        "page": page,
        "has_more": len(events) == per_page * page,
        "sources": [r["source"] for r in sources],
        "projects": [r["project"] for r in projects],
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_events.html", ctx)
    return templates.TemplateResponse(request, "timeline.html", ctx)


@app.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query(""),
    limit: int = Query(30),
):
    conn = get_db()
    events = search_events(conn, q, limit=limit) if q else []
    conn.close()

    ctx = {
        "events": events,
        "query": q,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_events.html", ctx)
    return templates.TemplateResponse(request, "search.html", ctx)


@app.get("/summary", response_class=HTMLResponse)
def summary_page(
    request: Request,
    kind: str = Query("standup"),
    days: int = Query(1),
    project: str | None = Query(None),
):
    return templates.TemplateResponse(
        request,
        "summary.html",
        {
            "kind": kind,
            "days": days,
            "project": project,
        },
    )


@app.get("/api/summary")
def api_summary(
    kind: str = Query("standup"),
    days: int = Query(1),
    project: str | None = Query(None),
):
    """Generate a summary via Claude. Called by HTMX."""
    import re

    from jarvis.brain import SYSTEM_PROMPTS, _call_claude, _format_events, _standup_prompt

    conn = get_db()
    events = query_events(conn, project=project, days=days, limit=200)
    conn.close()

    if not events:
        return HTMLResponse("<p>No events found for this period.</p>")

    if kind == "standup":
        system = _standup_prompt(days)
    elif kind in SYSTEM_PROMPTS:
        system = SYSTEM_PROMPTS[kind]
    else:
        system = SYSTEM_PROMPTS["weekly"]

    events_text = _format_events(events)
    result = _call_claude(system, events_text)

    # Basic markdown to HTML
    html = result
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html, flags=re.DOTALL)
    html = html.replace("\n\n", "<br><br>")
    return HTMLResponse(html)


@app.get("/sessions", response_class=HTMLResponse)
def sessions_page(
    request: Request,
    project: str | None = Query(None),
    limit: int = Query(20),
):
    conn = get_db()
    sessions = list_sessions(conn, project=project, limit=limit)
    conn.close()

    return templates.TemplateResponse(
        request,
        "sessions.html",
        {
            "sessions": sessions,
            "project": project,
        },
    )
