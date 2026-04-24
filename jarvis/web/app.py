from __future__ import annotations

import json
import subprocess
import uuid as uuid_mod
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from jarvis.db import (
    add_repo_path,
    delete_repo_path,
    event_count,
    get_db,
    list_repo_paths,
    list_sessions,
    query_events,
    search_events,
    set_repo_path_account,
    set_repo_path_enabled,
    update_pr_cache,
)
from jarvis.patterns import (
    collaboration_frequency,
    context_switches,
    day_of_week_distribution,
    project_distribution,
    source_distribution,
    time_of_day_distribution,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Jarvis Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse(url="/upcoming", status_code=302)


@app.get("/timeline", response_class=HTMLResponse)
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


@app.get("/upcoming", response_class=HTMLResponse)
def upcoming(request: Request):
    import zoneinfo as _zi
    from datetime import UTC, date
    from datetime import datetime as dt
    from datetime import time as dtime

    conn = get_db()
    try:
        _tz = _zi.ZoneInfo("localtime")
    except Exception:
        _tz = UTC
    _today = date.today()
    today_start = dt.combine(_today, dtime.min, tzinfo=_tz).astimezone(UTC)
    today_end = dt.combine(_today, dtime.max, tzinfo=_tz).astimezone(UTC)

    rows = conn.execute(
        """SELECT title, happened_at, url, body,
                  json_extract(metadata,'$.location') as location,
                  json_extract(metadata,'$.meet_link') as meet_link,
                  json_extract(metadata,'$.attendee_count') as attendee_count,
                  json_extract(metadata,'$.account') as account,
                  json_extract(metadata,'$.status') as status
           FROM events
           WHERE source='gcal'
             AND happened_at >= ? AND happened_at <= ?
           ORDER BY happened_at ASC""",
        (today_start.isoformat(), today_end.isoformat()),
    ).fetchall()

    meetings = []
    for r in rows:
        m = dict(r)
        try:
            ts = dt.fromisoformat(m["happened_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            m["time_local"] = ts.astimezone(_tz).strftime("%-I:%M %p")
            m["happened_at_epoch"] = int(ts.timestamp() * 1000)
        except Exception:
            m["time_local"] = (m["happened_at"] or "")[:16].replace("T", " ")
            m["happened_at_epoch"] = 0
        meetings.append(m)

    active = _subscriptions_active(conn)
    blockers = [
        _add_badges(s)
        for s in active
        if s.get("ci_status") == "failed" or s.get("review_decision") == "CHANGES_REQUESTED"
    ]

    conn.close()
    return templates.TemplateResponse(
        request,
        "upcoming.html",
        {
            "meetings": meetings,
            "blockers": blockers,
            "today": date.today(),
        },
    )


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


@app.get("/insights", response_class=HTMLResponse)
def insights_page(
    request: Request,
    days: int = Query(30),
):
    conn = get_db()
    ctx = {
        "days": days,
        "time_of_day": time_of_day_distribution(conn, days),
        "day_of_week": day_of_week_distribution(conn, days),
        "sources": source_distribution(conn, days),
        "projects": project_distribution(conn, days),
        "collaborators": collaboration_frequency(conn, days),
        "context_switches": context_switches(conn, min(days, 14)),
    }
    conn.close()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "insights.html", ctx)
    return templates.TemplateResponse(request, "insights.html", ctx)


@app.get("/api/suggestions")
def api_suggestions():
    """Return pending suggestions as JSON."""
    from jarvis.suggestions import evaluate_all, get_pending

    conn = get_db()
    evaluate_all(conn)
    pending = get_pending(conn)
    conn.close()
    return [
        {"rule_id": s.rule_id, "message": s.message, "action": s.action, "priority": s.priority}
        for s in pending
    ]


@app.post("/api/ingest")
def api_ingest(days: int = Query(7)):
    """Trigger ingest synchronously. Returns logs + summary as HTML."""
    try:
        from jarvis.ingest import ingest_all

        logs: list[str] = []
        total = ingest_all(days=days, log_collector=logs)
        lines_html = "".join(f"<div>{line}</div>" for line in logs if line.strip())
        return HTMLResponse(
            f'<div style="font-family:monospace;font-size:.8rem;'
            f'color:var(--pico-muted-color);margin-top:.5rem">{lines_html}</div>'
            f'<strong style="color:var(--pico-primary)">✓ {total} events ingested.</strong>'
        )
    except Exception as e:
        return HTMLResponse(f'<span style="color:var(--pico-color-red)">Ingest failed: {e}</span>')


@app.get("/sessions", response_class=HTMLResponse)
def sessions_page(
    request: Request,
    project: str | None = Query(None),
    limit: int = Query(20),
):
    conn = get_db()
    sessions = list_sessions(conn, project=project, limit=limit)
    claude_sessions = conn.execute(
        """SELECT title, happened_at,
                  json_extract(metadata,'$.session_id') as session_id,
                  json_extract(metadata,'$.branch') as branch,
                  json_extract(metadata,'$.cwd') as cwd,
                  json_extract(metadata,'$.turns') as turns,
                  COALESCE(json_extract(metadata,'$.last_message_at'), happened_at) as last_active
           FROM events WHERE source='claude_sessions'
           ORDER BY last_active DESC LIMIT 50"""
    ).fetchall()
    conn.close()

    return templates.TemplateResponse(
        request,
        "sessions.html",
        {
            "sessions": sessions,
            "claude_sessions": [dict(r) for r in claude_sessions],
            "project": project,
        },
    )


def _load_chat_history(session_id: str) -> list[dict]:
    """Read past turns from ~/.claude/projects/**/<session_id>.jsonl."""
    import glob

    pattern = str(Path.home() / ".claude" / "projects" / "**" / f"{session_id}.jsonl")
    matches = glob.glob(pattern, recursive=True)
    if not matches:
        return []
    turns = []
    try:
        for line in Path(matches[0]).read_text().splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("isSidechain"):
                continue
            role = obj.get("message", {}).get("role")
            if role not in ("user", "assistant"):
                continue
            content = obj.get("message", {}).get("content", "")
            if isinstance(content, list):
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            else:
                text = str(content)
            text = text.strip()
            if text:
                turns.append({"role": role, "text": text})
    except Exception:
        pass
    return turns


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, session: str | None = Query(None)):
    history_preview = ""
    history: list[dict] = []
    if session:
        conn = get_db()
        row = conn.execute(
            "SELECT title FROM events WHERE json_extract(metadata,'$.session_id')=? LIMIT 1",
            (session,),
        ).fetchone()
        conn.close()
        if row:
            history_preview = row["title"]
        history = _load_chat_history(session)
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"session_id": session or "", "history_preview": history_preview, "history": history},
    )


@app.post("/api/chat/stream")
def api_chat_stream(message: str = Form(...), session_id: str = Form("")):
    new_id = session_id or str(uuid_mod.uuid4())
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--bare", "--tools", ""]
    if session_id:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--session-id", new_id]

    def generate():
        yield f"data: {json.dumps({'session_id': new_id})}\n\n"
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write(message)
        proc.stdin.close()
        finished = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                t = obj.get("type")
                # stream-json --verbose: {type:"assistant", message:{content:[{type:"text",text:"..."}]}}
                if t == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if block.get("type") == "text" and block.get("text"):
                            yield f"data: {json.dumps({'text': block['text']})}\n\n"
                elif t == "result":
                    finished = True
                    if obj.get("is_error"):
                        yield f"data: {json.dumps({'error': obj.get('result', 'Claude returned an error')})}\n\n"
                    yield 'data: {"done": true}\n\n'
            except Exception:
                pass
        stderr_out = proc.stderr.read().strip()
        proc.wait()
        if not finished:
            msg = stderr_out or f"claude exited with code {proc.returncode}"
            yield f"data: {json.dumps({'error': msg})}\n\n"
            yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# PR Workspace
# ---------------------------------------------------------------------------

_IDE_CANDIDATES = [
    ("IntelliJ IDEA", "IntelliJ IDEA.app", "idea://open?file={path}"),
    ("VS Code", "Visual Studio Code.app", "vscode://file/{path}"),
    ("Cursor", "Cursor.app", "cursor://file/{path}"),
    ("Zed", "Zed.app", "zed://{path}"),
]


def _detect_ide() -> tuple[str, str] | None:
    """Return (ide_name, url_template) for the first installed IDE, or None."""
    apps = Path("/Applications")
    for name, bundle, url_tpl in _IDE_CANDIDATES:
        if (apps / bundle).exists():
            return name, url_tpl
    return None


def _gh(*args: str, repo: str | None = None, env: dict | None = None) -> dict | list | None:
    """Run a gh command and return parsed JSON, or None on failure."""
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _repo_encode(repo: str) -> str:
    return repo.replace("/", "--")


def _repo_decode(encoded: str) -> str:
    return encoded.replace("--", "/", 1)


def _local_path_for_repo(repo: str) -> Path | None:
    """Return local checkout path if the repo is in DB repo_paths or git_local.repo_paths."""
    try:
        from jarvis.config import JarvisConfig

        config = JarvisConfig.load()
        conn = get_db()
        db_paths = [row["path"] for row in list_repo_paths(conn)]
        conn.close()

        all_paths = db_paths + list(config.git_local.repo_paths or [])
        repo_name = repo.split("/")[-1]
        for p in all_paths:
            lp = Path(p).expanduser()
            if lp.name == repo_name and (lp / ".git").exists():
                return lp
    except Exception:
        pass
    return None


def _subscriptions_active(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pr_subscriptions WHERE dismissed=0 AND state='open' ORDER BY subscribed_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _subscriptions_dismissed(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pr_subscriptions WHERE dismissed=1 ORDER BY subscribed_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _subscription_upsert(conn, repo: str, pr_number: int, data: dict) -> None:
    from datetime import UTC, datetime

    from ulid import ULID

    conn.execute(
        """INSERT INTO pr_subscriptions
               (id, repo, pr_number, title, author, branch, pr_url, state, subscribed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
           ON CONFLICT(repo, pr_number) DO UPDATE SET
               title=excluded.title, author=excluded.author,
               branch=excluded.branch, pr_url=excluded.pr_url""",
        (
            str(ULID()),
            repo,
            pr_number,
            data.get("title"),
            data.get("author", {}).get("login") if isinstance(data.get("author"), dict) else None,
            data.get("headRefName"),
            data.get("url"),
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def _subscription_delete(conn, repo: str, pr_number: int) -> None:
    conn.execute("DELETE FROM pr_subscriptions WHERE repo=? AND pr_number=?", (repo, pr_number))
    conn.commit()


def _ci_badge(value: list | str | None) -> str:
    """Accept a statusCheckRollup list (from gh) or a cached string (from DB)."""
    if isinstance(value, list):
        if not value:
            return '<span style="color:var(--pico-muted-color)">–</span>'
        statuses = {r.get("conclusion") or r.get("status") for r in value}
        if "FAILURE" in statuses or "failure" in statuses:
            return '<span style="color:#f87171">✗ CI Failed</span>'
        if all(s in ("SUCCESS", "success", "NEUTRAL", "SKIPPED") for s in statuses if s):
            return '<span style="color:#4ade80">✓ CI Passed</span>'
        return '<span style="color:var(--pico-muted-color)">⏳ Running</span>'
    # Cached string from DB
    if value == "passed":
        return '<span style="color:#4ade80">✓ CI Passed</span>'
    if value == "failed":
        return '<span style="color:#f87171">✗ CI Failed</span>'
    if value == "running":
        return '<span style="color:var(--pico-muted-color)">⏳ Running</span>'
    return '<span style="color:var(--pico-muted-color)">–</span>'


def _review_badge(decision: str | None) -> str:
    if decision == "APPROVED":
        return '<span style="color:#4ade80">✓ Approved</span>'
    if decision == "CHANGES_REQUESTED":
        return '<span style="color:#f87171">↩ Changes requested</span>'
    if decision and decision not in ("", "REVIEW_REQUIRED"):
        return f'<span style="color:var(--pico-muted-color)">{decision}</span>'
    return '<span style="color:var(--pico-muted-color)">Review pending</span>'


def _parse_ci_status(pr_data: dict) -> str | None:
    """Collapse statusCheckRollup into a simple string for DB storage."""
    rollup = pr_data.get("statusCheckRollup") or []
    if not rollup:
        return None
    statuses = {r.get("conclusion") or r.get("status") for r in rollup}
    if "FAILURE" in statuses or "failure" in statuses:
        return "failed"
    if all(s in ("SUCCESS", "success", "NEUTRAL", "SKIPPED") for s in statuses if s):
        return "passed"
    return "running"


def _token_for_repo(conn, repo: str) -> str | None:
    """Return a GH_TOKEN for the account associated with this repo in DB paths."""
    for row in list_repo_paths(conn):
        path = str(Path(row["path"]).expanduser())
        if _remote_for_local_repo(path) == repo and row.get("gh_account"):
            return _gh_token(row["gh_account"])
    return None


def _add_badges(sub: dict) -> dict:
    """Attach ci_badge and review_badge HTML to a subscription dict (uses cached DB fields)."""
    sub["ci_badge"] = _ci_badge(sub.get("ci_status"))
    sub["review_badge"] = _review_badge(sub.get("review_decision"))
    return sub


def _firefox_installed() -> bool:
    return Path("/Applications/Firefox.app").exists()


def _firefox_profiles() -> list[dict]:
    """Return list of {name, path} dicts from Firefox Profile Groups SQLite.

    Firefox stores user-visible profile names ("Work", "Personal") in a SQLite
    database under Profile Groups, not in profiles.ini. Falls back to profiles.ini
    Name= values if the SQLite is unavailable.
    """
    import sqlite3

    profile_groups_dir = Path.home() / "Library/Application Support/Firefox/Profile Groups"
    if profile_groups_dir.exists():
        for sqlite_path in profile_groups_dir.glob("*.sqlite"):
            try:
                pconn = sqlite3.connect(str(sqlite_path))
                pconn.row_factory = sqlite3.Row
                rows = pconn.execute("SELECT name, path FROM Profiles ORDER BY id").fetchall()
                pconn.close()
                if rows:
                    return [{"name": r["name"], "path": r["path"]} for r in rows]
            except Exception:
                pass

    # Fallback: read profiles.ini
    import configparser

    ini = Path.home() / "Library/Application Support/Firefox/profiles.ini"
    if not ini.exists():
        return []
    cfg = configparser.ConfigParser()
    cfg.read(str(ini))
    return [
        {"name": cfg[s]["Name"], "path": cfg[s].get("Path", "")}
        for s in cfg.sections()
        if s.startswith("Profile") and "Name" in cfg[s]
    ]


def _profile_for_account(conn, account: str) -> str | None:
    from jarvis.db import kv_get

    if not account:
        return None
    # Direct gh-account → profile mapping (set in PRs settings panel)
    profile = kv_get(conn, f"browser_profile:{account}")
    if profile:
        return profile
    # Indirect: gcal/calendar account name → gh account → profile
    gh_account = kv_get(conn, f"gcal_gh_account:{account}")
    if gh_account:
        return kv_get(conn, f"browser_profile:{gh_account}")
    return None


def _browser_profile_fragment(conn) -> str:
    from jarvis.db import kv_get

    if not _firefox_installed():
        return '<p style="font-size:.85em;color:var(--pico-muted-color)">Firefox not found — links open in default browser.</p>'
    profiles = _firefox_profiles()
    accounts = _gh_accounts()
    if not accounts:
        return (
            '<p style="font-size:.85em;color:var(--pico-muted-color)">No gh accounts detected.</p>'
        )
    rows = ""
    for acct in accounts:
        current = kv_get(conn, f"browser_profile:{acct}") or ""
        opts = '<option value="">— default browser —</option>'
        for p in profiles:
            sel = " selected" if p["path"] == current else ""
            opts += f'<option value="{p["path"]}"{sel}>{p["name"]}</option>'
        rows += (
            f'<div style="display:flex;align-items:center;gap:.75rem;padding:.3rem 0;'
            f'border-bottom:1px solid var(--pico-muted-border-color)">'
            f'<span style="font-size:.85em;min-width:9rem"><code>{acct}</code></span>'
            f'<select style="font-size:.8rem;padding:.15rem .4rem;margin:0"'
            f' name="profile"'
            f' hx-post="/api/settings/browser-profile/{acct}"'
            f' hx-target="#browser-profile-list" hx-swap="innerHTML"'
            f' hx-trigger="change">{opts}</select>'
            f"</div>"
        )
    return rows


def _badge_fragment(sub: dict) -> str:
    """Return just the badge span HTML for HTMX swap into #badges-{pr_number}."""
    return f"{sub['ci_badge']} &nbsp; {sub['review_badge']}"


@app.get("/prs", response_class=HTMLResponse)
def prs_page(
    request: Request,
    repo: str | None = Query(None),
    author: str | None = Query(None),
):
    conn = get_db()
    active = [_add_badges(s) for s in _subscriptions_active(conn)]
    dismissed = _subscriptions_dismissed(conn)

    # Attach gh_account to each sub so the template can pass it to /api/open-url
    # Build exact repo→account map from configured local paths
    repo_account_map: dict[str, str] = {}
    owner_account_map: dict[str, str] = {}  # fallback: owner prefix → account
    for r in list_repo_paths(conn):
        if not r.get("gh_account"):
            continue
        full_repo = _remote_for_local_repo(str(Path(r["path"]).expanduser()))
        if full_repo:
            repo_account_map[full_repo] = r["gh_account"]
            owner = full_repo.split("/")[0]
            owner_account_map.setdefault(owner, r["gh_account"])
    for sub in active:
        sub_repo = sub["repo"]
        account = repo_account_map.get(sub_repo)
        if not account:
            owner = sub_repo.split("/")[0] if "/" in sub_repo else sub_repo
            account = owner_account_map.get(owner, "")
        sub["gh_account"] = account

    # Build filter option lists from all active subs
    all_repos = sorted({s["repo"] for s in active})
    all_authors = sorted({s["author"] for s in active if s.get("author")})

    # Apply filters
    if repo:
        active = [s for s in active if s["repo"] == repo]
    if author:
        active = [s for s in active if s.get("author") == author]

    from jarvis.db import kv_get

    last_checked = kv_get(conn, "last_pr_check_at") or "Never"
    conn.close()

    ide = _detect_ide()
    return templates.TemplateResponse(
        request,
        "prs.html",
        {
            "subscriptions": active,
            "dismissed": dismissed,
            "last_checked": last_checked,
            "ide_name": ide[0] if ide else None,
            "all_repos": all_repos,
            "all_authors": all_authors,
            "filter_repo": repo or "",
            "filter_author": author or "",
        },
    )


def _gh_accounts() -> list[str]:
    """Return all gh-authenticated usernames."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Parse "✓ Logged in to github.com account USERNAME" lines
        import re

        return re.findall(r"account (\S+)", result.stderr + result.stdout)
    except Exception:
        return []


def _gh_token(account: str) -> str | None:
    """Return the auth token for a specific gh account."""
    try:
        r = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def _detect_account_for_repo(repo: str) -> str | None:
    """Return the first gh account that can access the repo, or None."""
    import os

    for account in _gh_accounts():
        token = _gh_token(account)
        if not token:
            continue
        r = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "name"],
            capture_output=True,
            text=True,
            timeout=8,
            env={**os.environ, "GH_TOKEN": token},
        )
        if r.returncode == 0:
            return account
    return None


def _remote_for_local_repo(path: str) -> str | None:
    """Extract owner/repo from a local git repo's remote URL."""
    try:
        result = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # SSH: git@github.com:owner/repo.git  or HTTPS: https://github.com/owner/repo.git
        import re

        m = re.search(r"github\.com[^:/]*[:/](.+?)(?:\.git)?$", url)
        return m.group(1) if m else None
    except Exception:
        return None


def _repos_from_local_paths(config) -> list[str]:
    """Return GitHub owner/repo strings inferred from git_local.repo_paths."""
    repos = []
    for p in config.git_local.repo_paths or []:
        path = str(Path(p).expanduser())
        repo = _remote_for_local_repo(path)
        if repo and repo not in repos:
            repos.append(repo)
    return repos


def _repos_from_db(conn) -> list[tuple[str, str | None]]:
    """Return (owner/repo, gh_account) pairs for enabled paths only."""
    result = []
    for row in list_repo_paths(conn):
        if not row.get("enabled", 1):
            continue
        path = str(Path(row["path"]).expanduser())
        repo = _remote_for_local_repo(path)
        if repo and not any(r == repo for r, _ in result):
            result.append((repo, row["gh_account"]))
    return result


@app.post("/api/prs/discover")
def api_prs_discover():
    """Search GitHub for open PRs — scans local repos + all gh accounts. Returns HTML fragment."""
    from jarvis.config import JarvisConfig

    config = JarvisConfig.load()
    conn = get_db()
    prs: list[dict] = []
    seen: set[str] = set()

    import os

    # Build (repo, gh_account) pairs: explicit config + DB paths + config git_local paths
    repo_accounts: list[tuple[str, str | None]] = [(r, None) for r in config.github.repos or []]
    for repo, acct in _repos_from_db(conn):
        if not any(r == repo for r, _ in repo_accounts):
            repo_accounts.append((repo, acct))
    conn.close()
    for r in _repos_from_local_paths(config):
        if not any(repo == r for repo, _ in repo_accounts):
            repo_accounts.append((r, None))

    # List open PRs in every known repo, using the correct gh account token
    for repo, acct in repo_accounts:
        token = _gh_token(acct) if acct else None
        env = {**os.environ, "GH_TOKEN": token} if token else None
        data = _gh(
            "pr",
            "list",
            "--json",
            "number,title,headRefName,url,author,reviewDecision,statusCheckRollup",
            "--state",
            "open",
            repo=repo,
            env=env,
        )
        if isinstance(data, list):
            for pr in data:
                key = f"{repo}#{pr['number']}"
                if key not in seen:
                    seen.add(key)
                    prs.append({**pr, "repo": repo})

    # Search by involvement across ALL authenticated gh accounts
    for account in _gh_accounts():
        token = _gh_token(account)
        env = {**os.environ, "GH_TOKEN": token} if token else None
        result = subprocess.run(
            [
                "gh",
                "search",
                "prs",
                "--involves",
                account,
                "--state",
                "open",
                "--json",
                "number,title,repository,url,author",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if result.returncode == 0:
            for pr in json.loads(result.stdout or "[]"):
                repo = pr.get("repository", {}).get("nameWithOwner", "")
                key = f"{repo}#{pr['number']}"
                if key and key not in seen:
                    seen.add(key)
                    prs.append({**pr, "repo": repo})

    if not prs:
        return HTMLResponse('<p style="color:var(--pico-muted-color)">No open PRs found.</p>')

    # Auto-subscribe all discovered PRs and write CI/review cache
    conn2 = get_db()
    for pr in prs:
        _subscription_upsert(conn2, pr["repo"], pr["number"], pr)
        ci = _parse_ci_status(pr)
        rd = pr.get("reviewDecision") or ""
        update_pr_cache(conn2, pr["repo"], pr["number"], ci, rd)
    conn2.close()

    new_count = len(prs)
    return HTMLResponse(
        f'<p style="color:#4ade80;font-size:.85em">'
        f"✓ {new_count} open PR{'s' if new_count != 1 else ''} synced — "
        f'<a href="/prs" style="color:#4ade80">refresh page</a> to see them.</p>'
    )


@app.post("/api/prs/subscribe")
def api_prs_subscribe(repo: str = Form(...), pr_number: int = Form(...)):
    pr_data = (
        _gh(
            "pr",
            "view",
            str(pr_number),
            "--json",
            "title,headRefName,url,author,reviewDecision,statusCheckRollup",
            repo=repo,
        )
        or {}
    )
    conn = get_db()
    _subscription_upsert(conn, repo, pr_number, pr_data)
    conn.close()
    return HTMLResponse('<span style="color:#4ade80">✓ Subscribed</span>')


@app.delete("/api/prs/{repo_encoded}/{pr_number}")
def api_prs_unsubscribe(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    _subscription_delete(conn, repo, pr_number)
    conn.close()
    return HTMLResponse("")


@app.post("/api/prs/{repo_encoded}/{pr_number}/dismiss")
def api_prs_dismiss(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    conn.execute(
        "UPDATE pr_subscriptions SET dismissed=1 WHERE repo=? AND pr_number=?",
        (repo, pr_number),
    )
    conn.commit()
    conn.close()
    return HTMLResponse("")


@app.post("/api/prs/{repo_encoded}/{pr_number}/undismiss")
def api_prs_undismiss(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    conn.execute(
        "UPDATE pr_subscriptions SET dismissed=0, state='open' WHERE repo=? AND pr_number=?",
        (repo, pr_number),
    )
    conn.commit()
    conn.close()
    return HTMLResponse("")


@app.get("/api/prs/{repo_encoded}/{pr_number}/refresh")
def api_pr_refresh(repo_encoded: str, pr_number: int):
    """Fetch live data for one PR, update cache, return badge HTML."""
    import os

    repo = _repo_decode(repo_encoded)
    conn = get_db()
    token = _token_for_repo(conn, repo)
    env = {**os.environ, "GH_TOKEN": token} if token else None
    data = _gh(
        "pr",
        "view",
        str(pr_number),
        "--json",
        "title,number,headRefName,url,author,reviewDecision,statusCheckRollup,state",
        repo=repo,
        env=env,
    )
    if data:
        ci = _parse_ci_status(data)
        rd = data.get("reviewDecision") or ""
        update_pr_cache(
            conn,
            repo,
            pr_number,
            ci,
            rd,
            title=data.get("title"),
            author=(data.get("author") or {}).get("login"),
            branch=data.get("headRefName"),
            pr_url=data.get("url"),
            state=(data.get("state") or "").lower() or None,
        )
        sub = {"ci_badge": _ci_badge(ci), "review_badge": _review_badge(rd)}
    else:
        sub = {"ci_badge": '<span style="color:#f87171">error</span>', "review_badge": ""}
    conn.close()
    return HTMLResponse(_badge_fragment(sub))


@app.post("/api/prs/refresh-all")
def api_prs_refresh_all():
    """Fetch live data for all active PRs and update cache. Returns status HTML."""
    import os

    conn = get_db()
    subs = _subscriptions_active(conn)
    updated = 0
    for sub in subs:
        repo = sub["repo"]
        token = _token_for_repo(conn, repo)
        env = {**os.environ, "GH_TOKEN": token} if token else None
        data = _gh(
            "pr",
            "view",
            str(sub["pr_number"]),
            "--json",
            "title,number,headRefName,url,author,reviewDecision,statusCheckRollup,state",
            repo=repo,
            env=env,
        )
        if data:
            ci = _parse_ci_status(data)
            rd = data.get("reviewDecision") or ""
            update_pr_cache(
                conn,
                repo,
                sub["pr_number"],
                ci,
                rd,
                title=data.get("title"),
                author=(data.get("author") or {}).get("login"),
                branch=data.get("headRefName"),
                pr_url=data.get("url"),
                state=(data.get("state") or "").lower() or None,
            )
            updated += 1
    conn.close()
    return HTMLResponse(
        f'<span style="color:#4ade80;font-size:.85em">✓ {updated} PR{"s" if updated != 1 else ""} refreshed</span>'
    )


@app.post("/api/open-url")
def api_open_url(url: str = Form(...), gh_account: str = Form("")):
    """Open a URL in the correct Firefox profile (or default browser) for the given account."""
    import subprocess

    conn = get_db()
    profile_path = _profile_for_account(conn, gh_account or None)
    conn.close()
    if _firefox_installed() and profile_path:
        # Resolve relative path (e.g. "Profiles/d55fx6mi.default-release") to absolute
        base = Path.home() / "Library/Application Support/Firefox"
        abs_profile = base / profile_path
        firefox_bin = "/Applications/Firefox.app/Contents/MacOS/firefox"
        subprocess.Popen(
            [firefox_bin, "--no-remote", "--profile", str(abs_profile), "--new-window", url]
        )
    else:
        subprocess.Popen(["open", url])
    return HTMLResponse("")


def _gcal_account_map_fragment(conn) -> str:
    """HTML fragment: map each gcal account name to a gh account for Firefox profile lookup."""
    from jarvis.config import JarvisConfig
    from jarvis.db import kv_get

    gh_accounts = _gh_accounts()
    if not gh_accounts:
        return (
            '<p style="font-size:.85em;color:var(--pico-muted-color)">No gh accounts detected.</p>'
        )
    try:
        gcal_accounts = [a.name for a in JarvisConfig.load().gcal.accounts]
    except Exception:
        gcal_accounts = []
    if not gcal_accounts:
        return '<p style="font-size:.85em;color:var(--pico-muted-color)">No gcal accounts configured.</p>'
    rows = ""
    for cal_acct in gcal_accounts:
        current = kv_get(conn, f"gcal_gh_account:{cal_acct}") or ""
        opts = '<option value="">— none —</option>'
        for gh in gh_accounts:
            sel = " selected" if gh == current else ""
            opts += f'<option value="{gh}"{sel}>{gh}</option>'
        rows += (
            f'<div style="display:flex;align-items:center;gap:.75rem;padding:.3rem 0;'
            f'border-bottom:1px solid var(--pico-muted-border-color)">'
            f'<span style="font-size:.85em;min-width:9rem"><code>{cal_acct}</code></span>'
            f'<select name="profile" style="font-size:.8rem;padding:.15rem .4rem;margin:0"'
            f' hx-post="/api/settings/gcal-account/{cal_acct}"'
            f' hx-target="#gcal-account-map-list" hx-swap="innerHTML"'
            f' hx-trigger="change">{opts}</select>'
            f"</div>"
        )
    return rows


@app.get("/api/settings/gcal-account-map", response_class=HTMLResponse)
def settings_gcal_account_map_get():
    conn = get_db()
    html = _gcal_account_map_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/gcal-account/{cal_account}", response_class=HTMLResponse)
def settings_gcal_account_set(cal_account: str, profile: str = Form("")):
    from jarvis.db import kv_set

    conn = get_db()
    kv_set(conn, f"gcal_gh_account:{cal_account}", profile)
    html = _gcal_account_map_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.get("/api/settings/browser-profiles", response_class=HTMLResponse)
def settings_browser_profiles_get():
    conn = get_db()
    html = _browser_profile_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/browser-profile/{account}", response_class=HTMLResponse)
def settings_browser_profile_set(account: str, profile: str = Form("")):
    from jarvis.db import kv_set

    conn = get_db()
    kv_set(conn, f"browser_profile:{account}", profile)
    html = _browser_profile_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.get("/api/prs/{repo_encoded}/{pr_number}/detail")
def api_pr_detail(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)

    pr = _gh(
        "pr",
        "view",
        str(pr_number),
        "--json",
        (
            "title,body,number,headRefName,url,author,"
            "reviewDecision,statusCheckRollup,changedFiles,additions,deletions,"
            "reviews,comments"
        ),
        repo=repo,
    )
    if pr is None:
        return HTMLResponse('<p style="color:#f87171">Could not fetch PR details.</p>')

    # Review comments (inline threads)
    threads_data = _gh("api", f"repos/{repo}/pulls/{pr_number}/comments") or []

    # Group threads by original_position/path
    threads: dict[str, list[dict]] = {}
    for c in threads_data if isinstance(threads_data, list) else []:
        key = c.get("path", "") + ":" + str(c.get("original_position", ""))
        threads.setdefault(key, []).append(c)

    # Local path + IDE
    local_path = _local_path_for_repo(repo)
    ide = _detect_ide()
    ide_url = None
    if local_path and ide:
        ide_url = ide[1].format(path=str(local_path))

    # Build HTML
    encoded = _repo_encode(repo)
    body_html = (pr.get("body") or "").replace("\n", "<br>")
    ci_html = _ci_badge(pr.get("statusCheckRollup"))
    review_html = _review_badge(pr.get("reviewDecision"))
    branch = pr.get("headRefName", "")
    changed = pr.get("changedFiles", 0)
    adds = pr.get("additions", 0)
    dels = pr.get("deletions", 0)

    checks_rows = ""
    for chk in pr.get("statusCheckRollup") or []:
        name = chk.get("name") or chk.get("context", "")
        status = chk.get("conclusion") or chk.get("status", "")
        link = chk.get("detailsUrl") or chk.get("targetUrl") or "#"
        ok = status in ("SUCCESS", "success")
        fail = status in ("FAILURE", "failure")
        icon = "✓" if ok else ("✗" if fail else "⏳")
        checks_rows += (
            f"<tr><td>{icon} {name}</td>"
            f'<td><a href="{link}" target="_blank" style="font-size:.8em">details</a></td></tr>'
        )

    threads_html = ""
    for key, comments in threads.items():
        path = comments[0].get("path", "")
        threads_html += f'<details><summary style="font-size:.85em;cursor:pointer">{path}</summary>'
        for c in comments:
            author = c.get("user", {}).get("login", "")
            body = c.get("body", "").replace("\n", "<br>")
            comment_id = c.get("id", "")
            threads_html += (
                f'<div style="border-left:3px solid var(--pico-muted-border-color);'
                f'padding:.5rem;margin:.5rem 0">'
                f'<strong style="font-size:.85em">{author}</strong><br>{body}'
                f"</div>"
            )
            threads_html += (
                f'<form hx-post="/api/prs/{encoded}/{pr_number}/reply/{comment_id}" '
                f'hx-target="this" hx-swap="outerHTML" style="margin:.25rem 0">'
                f'<input name="body" placeholder="Reply…" style="font-size:.8rem;margin-bottom:.25rem">'
                f'<button type="submit" style="font-size:.75rem;padding:.2rem .6rem">Reply</button>'
                f"</form>"
            )
        threads_html += "</details>"

    ide_btn = ""
    if ide_url and ide:
        ide_btn = (
            f'<a href="{ide_url}" style="font-size:.8rem;margin-left:.5rem" '
            f'role="button" class="outline">Open in {ide[0]}</a>'
        )
    elif not local_path:
        ide_btn = f'<code style="font-size:.75rem">gh repo clone {repo}</code>'

    html = f"""
<div style="padding:1rem;border:1px solid var(--pico-muted-border-color);border-radius:6px;margin-top:.5rem">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">
    <div>
      <strong>#{pr_number} {pr.get("title", "")}</strong>
      <span style="font-size:.8em;color:var(--pico-muted-color);margin-left:.5rem">
        branch: <code>{branch}</code>
      </span>
    </div>
    <div>
      <a href="{pr.get("url", "#")}" target="_blank" style="font-size:.8rem" role="button" class="outline">
        View on GitHub ↗
      </a>
      {ide_btn}
    </div>
  </div>
  <div style="margin:.5rem 0;font-size:.9em">{ci_html} &nbsp; {review_html}</div>
  <div style="font-size:.8em;color:var(--pico-muted-color)">{changed} files &nbsp; +{adds} −{dels}</div>
  {f'<p style="font-size:.9em;margin-top:.75rem">{body_html}</p>' if body_html else ""}
  {f'<table style="font-size:.8em;margin:.5rem 0"><tbody>{checks_rows}</tbody></table>' if checks_rows else ""}
  {f'<h4 style="font-size:.9em;margin-top:1rem">Review threads</h4>{threads_html}' if threads_html else ""}
  <div style="margin-top:1rem">
    <button style="font-size:.75rem;padding:.2rem .6rem"
      hx-post="/api/prs/{encoded}/{pr_number}/review"
      hx-target="#pr-review-{pr_number}"
      hx-swap="innerHTML"
      hx-on:htmx:before-request="this.disabled=true;this.textContent='🤖 Reviewing…'"
      hx-on:htmx:after-request="this.disabled=false;this.textContent='🤖 Review with Claude'">
      🤖 Review with Claude
    </button>
    <div id="pr-review-{pr_number}" style="margin-top:.5rem;font-size:.85em"></div>
  </div>
</div>
"""
    return HTMLResponse(html)


@app.post("/api/prs/{repo_encoded}/{pr_number}/review")
def api_pr_review(repo_encoded: str, pr_number: int):
    """Claude reviews the PR diff and posts it as a GitHub review comment."""
    import re

    repo = _repo_decode(repo_encoded)

    # Get diff
    diff_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
        timeout=30,
    )
    diff = diff_result.stdout[:6000] if diff_result.returncode == 0 else ""

    if not diff:
        return HTMLResponse('<span style="color:#f87171">Could not fetch PR diff.</span>')

    prompt = (
        "Review this pull request diff. Be concise — 3-5 bullet points covering: "
        "correctness issues, potential bugs, style/clarity suggestions. "
        "If it looks good, say so briefly.\n\n"
        f"```diff\n{diff}\n```"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--bare", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        review_text = result.stdout.strip() or "No review generated."
    except Exception as e:
        return HTMLResponse(f'<span style="color:#f87171">Claude error: {e}</span>')

    # Post as GitHub PR comment
    subprocess.run(
        [
            "gh",
            "pr",
            "comment",
            str(pr_number),
            "--repo",
            repo,
            "--body",
            f"🤖 **Jarvis Claude Review**\n\n{review_text}",
        ],
        capture_output=True,
        timeout=15,
    )

    # Render as HTML
    html = review_text
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^[-•] (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html, flags=re.DOTALL)
    html = html.replace("\n\n", "<br>")
    return HTMLResponse(
        f'<div style="border-left:3px solid var(--pico-primary);padding:.5rem .75rem">'
        f"{html}"
        f'<div style="font-size:.75em;color:var(--pico-muted-color);margin-top:.25rem">'
        f"↑ Posted as comment on GitHub</div></div>"
    )


@app.post("/api/prs/{repo_encoded}/{pr_number}/reply/{comment_id}")
def api_pr_reply(repo_encoded: str, pr_number: int, comment_id: int, body: str = Form(...)):
    repo = _repo_decode(repo_encoded)
    subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/comments/{comment_id}/replies", "-f", f"body={body}"],
        capture_output=True,
        timeout=15,
    )
    return HTMLResponse(
        f'<div style="font-size:.8em;color:var(--pico-muted-color)">↑ Replied: {body}</div>'
    )


# ---------------------------------------------------------------------------
# Repo path settings
# ---------------------------------------------------------------------------


def _repo_paths_fragment(conn) -> str:
    rows = list_repo_paths(conn)
    if not rows:
        return '<p style="font-size:.85em;color:var(--pico-muted-color);margin:.5rem 0">No paths added yet.</p>'
    accounts = _gh_accounts()
    items = ""
    for row in rows:
        path = row["path"]
        repo = _remote_for_local_repo(str(Path(path).expanduser()))
        current_acct = row["gh_account"] or ""
        if repo:
            repo_label = f'<span style="color:var(--pico-muted-color)">→ {repo}</span>'
            opts = "".join(
                f'<option value="{a}"{" selected" if a == current_acct else ""}>{a}</option>'
                for a in accounts
            )
            acct_select = (
                f'<select style="font-size:.75rem;padding:.1rem .3rem;margin:0 .4rem;'
                f"border:1px solid var(--pico-muted-border-color);background:transparent;"
                f'color:var(--pico-muted-color);border-radius:4px"'
                f' name="gh_account"'
                f' hx-post="/api/settings/repo-paths/{row["id"]}/account"'
                f' hx-target="#repo-paths-list" hx-swap="innerHTML"'
                f' hx-trigger="change">{opts}</select>'
                if accounts
                else f'<span style="font-size:.75rem;color:var(--pico-muted-color);margin:0 .4rem">'
                f"[{current_acct or 'no account'}]</span>"
            )
        else:
            repo_label = '<span style="color:var(--pico-muted-color)">(not a GitHub repo)</span>'
            acct_select = ""
        enabled = row.get("enabled", 1)
        checked = "checked" if enabled else ""
        muted = "" if enabled else "opacity:.45;"
        items += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:.3rem 0;border-bottom:1px solid var(--pico-muted-border-color);{muted}">'
            f'<span style="font-size:.85em;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">'
            f'<input type="checkbox" {checked} style="margin:0;width:1rem;height:1rem;cursor:pointer"'
            f' hx-post="/api/settings/repo-paths/{row["id"]}/toggle"'
            f' hx-target="#repo-paths-list" hx-swap="innerHTML" hx-trigger="change">'
            f"<code>{path}</code> {repo_label}{acct_select}</span>"
            f'<button style="font-size:.75rem;padding:.15rem .5rem;background:none;'
            f'border:1px solid var(--pico-muted-border-color);color:var(--pico-muted-color)"'
            f' hx-delete="/api/settings/repo-paths/{row["id"]}"'
            f' hx-target="#repo-paths-list" hx-swap="innerHTML">✕</button>'
            f"</div>"
        )
    return items


@app.get("/api/settings/repo-paths", response_class=HTMLResponse)
def settings_repo_paths_get():
    conn = get_db()
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/repo-paths", response_class=HTMLResponse)
def settings_repo_paths_add(path: str = Form(...)):
    p = path.strip()
    conn = get_db()
    row_id = add_repo_path(conn, p)
    repo = _remote_for_local_repo(str(Path(p).expanduser()))
    if repo:
        account = _detect_account_for_repo(repo)
        if account:
            set_repo_path_account(conn, row_id, account)
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/repo-paths/browse", response_class=HTMLResponse)
def settings_repo_paths_browse():
    """Open a native macOS folder picker and add the chosen path."""
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Select a repo or a folder containing repos")',
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return HTMLResponse("")  # user cancelled — return empty, list unchanged
        chosen = result.stdout.strip().rstrip("/")
    except Exception as e:
        return HTMLResponse(
            f'<p style="color:#f87171;font-size:.85em">Folder picker error: {e}</p>'
        )

    # If the chosen folder itself is a git repo, add it directly.
    # Otherwise scan one level deep for git repos (handles "~/code" parent folders).
    chosen_path = Path(chosen)
    candidates: list[str] = []
    if (chosen_path / ".git").exists():
        candidates = [chosen]
    else:
        for sub in sorted(chosen_path.iterdir()):
            if sub.is_dir() and (sub / ".git").exists():
                candidates.append(str(sub))

    if not candidates:
        return HTMLResponse(
            '<p style="color:#f87171;font-size:.85em">No git repos found in that folder.</p>'
        )

    conn = get_db()
    for p in candidates:
        row_id = add_repo_path(conn, p)
        repo = _remote_for_local_repo(p)
        if repo:
            account = _detect_account_for_repo(repo)
            if account:
                set_repo_path_account(conn, row_id, account)
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.delete("/api/settings/repo-paths/{path_id}", response_class=HTMLResponse)
def settings_repo_paths_delete(path_id: str):
    conn = get_db()
    delete_repo_path(conn, path_id)
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/repo-paths/{path_id}/account", response_class=HTMLResponse)
def settings_repo_paths_set_account(path_id: str, gh_account: str = Form(...)):
    conn = get_db()
    set_repo_path_account(conn, path_id, gh_account or None)
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)


@app.post("/api/settings/repo-paths/{path_id}/toggle", response_class=HTMLResponse)
def settings_repo_paths_toggle(path_id: str):
    conn = get_db()
    row = conn.execute("SELECT enabled FROM repo_paths WHERE id=?", (path_id,)).fetchone()
    if row:
        set_repo_path_enabled(conn, path_id, not row["enabled"])
    html = _repo_paths_fragment(conn)
    conn.close()
    return HTMLResponse(html)
