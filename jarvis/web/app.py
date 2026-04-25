"""FastAPI backend for the Jarvis dashboard.

Serves a React SPA from jarvis/web/static/ and exposes JSON endpoints under /api/*.
The HTML-fragment endpoints used by the old HTMX frontend have been removed.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid as uuid_mod
from datetime import UTC, date, datetime
from datetime import datetime as dt
from datetime import time as dtime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from jarvis.db import (
    add_repo_path,
    delete_repo_path,
    event_count,
    get_db,
    kv_get,
    kv_set,
    list_repo_paths,
    list_sessions,
    query_events,
    search_events,
    set_pr_chat_session,
    set_pr_priority,
    set_pr_watch_state,
    set_repo_path_account,
    set_repo_path_enabled,
    subscriptions_dismissed,
    subscriptions_later,
    subscriptions_pending,
    subscriptions_watching,
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
from jarvis.pr_refresh import refresh_one

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_JARVIS_HOME = Path.home() / ".jarvis"
_log_path = _JARVIS_HOME / "jarvis.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)
_file_handler = TimedRotatingFileHandler(
    str(_log_path), when="midnight", backupCount=7, encoding="utf-8"
)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
_file_handler.setFormatter(_fmt)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), _file_handler],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app + static SPA
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Jarvis Dashboard")

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


# ---------------------------------------------------------------------------
# Helpers — gh CLI / Firefox profile / IDE detection
# ---------------------------------------------------------------------------


def _gh(*args: str, repo: str | None = None, env: dict | None = None) -> dict | list | None:
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


def _parse_ci_status(pr_data: dict) -> str | None:
    rollup = pr_data.get("statusCheckRollup") or []
    if not rollup:
        return None
    statuses = {r.get("conclusion") or r.get("status") for r in rollup}
    if "FAILURE" in statuses or "failure" in statuses:
        return "failed"
    if all(s in ("SUCCESS", "success", "NEUTRAL", "SKIPPED") for s in statuses if s):
        return "passed"
    return "running"


def _subscription_upsert(
    conn, repo: str, pr_number: int, data: dict, gh_username: str | None = None
) -> None:
    from ulid import ULID

    author_login = (
        data.get("author", {}).get("login") if isinstance(data.get("author"), dict) else None
    )
    watch_state = "watching" if (gh_username and author_login == gh_username) else "pending"
    conn.execute(
        """INSERT INTO pr_subscriptions
               (id, repo, pr_number, title, author, branch, pr_url, state, subscribed_at, watch_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
           ON CONFLICT(repo, pr_number) DO UPDATE SET
               title=excluded.title, author=excluded.author,
               branch=excluded.branch, pr_url=excluded.pr_url""",
        (
            str(ULID()),
            repo,
            pr_number,
            data.get("title"),
            author_login,
            data.get("headRefName"),
            data.get("url"),
            datetime.now(UTC).isoformat(),
            watch_state,
        ),
    )
    conn.commit()


def _subscription_delete(conn, repo: str, pr_number: int) -> None:
    conn.execute("DELETE FROM pr_subscriptions WHERE repo=? AND pr_number=?", (repo, pr_number))
    conn.commit()


def _subscriptions_active(conn) -> list[dict]:
    return subscriptions_watching(conn)


def _firefox_installed() -> bool:
    return Path("/Applications/Firefox.app").exists()


def _firefox_profiles() -> list[dict]:
    import configparser
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


def _profile_for_account(conn, account: str | None, jira_host: str | None = None) -> str | None:
    """Resolve a Firefox profile path for an open-url request.

    Lookup order:
      1. browser_profile:<account>           — direct gh account mapping
      2. gcal_gh_account:<account> → browser_profile:<gh>   — gcal fallback
      3. jira_profile:<jira_host>            — Jira host mapping
    """
    if account:
        profile = kv_get(conn, f"browser_profile:{account}")
        if profile:
            return profile
        gh_account = kv_get(conn, f"gcal_gh_account:{account}")
        if gh_account:
            profile = kv_get(conn, f"browser_profile:{gh_account}")
            if profile:
                return profile
    if jira_host:
        profile = kv_get(conn, f"jira_profile:{jira_host}")
        if profile:
            return profile
    return None


def _gh_accounts() -> list[str]:
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10
        )
        import re

        return re.findall(r"account (\S+)", result.stderr + result.stdout)
    except Exception:
        return []


def _gh_token(account: str) -> str | None:
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
        import re

        m = re.search(r"github\.com[^:/]*[:/](.+?)(?:\.git)?$", url)
        return m.group(1) if m else None
    except Exception:
        return None


def _repos_from_local_paths(config) -> list[str]:
    repos = []
    for p in config.git_local.repo_paths or []:
        path = str(Path(p).expanduser())
        repo = _remote_for_local_repo(path)
        if repo and repo not in repos:
            repos.append(repo)
    return repos


def _repos_from_db(conn) -> list[tuple[str, str | None]]:
    result = []
    for row in list_repo_paths(conn):
        if not row.get("enabled", 1):
            continue
        path = str(Path(row["path"]).expanduser())
        repo = _remote_for_local_repo(path)
        if repo and not any(r == repo for r, _ in result):
            result.append((repo, row["gh_account"]))
    return result


def _local_path_for_repo(repo: str) -> Path | None:
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


def _token_for_repo(conn, repo: str) -> str | None:
    for row in list_repo_paths(conn):
        path = str(Path(row["path"]).expanduser())
        if _remote_for_local_repo(path) == repo and row.get("gh_account"):
            return _gh_token(row["gh_account"])
    return None


def _claude_models() -> list[dict]:
    """Read model IDs from ~/.claude/settings.json env vars. Falls back to known defaults."""
    _defaults = [
        {"label": "Opus 4.7", "id": "claude-opus-4-7"},
        {"label": "Sonnet 4.6", "id": "claude-sonnet-4-6"},
        {"label": "Haiku 4.5", "id": "claude-haiku-4-5-20251001"},
    ]
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return _defaults
    try:
        data = json.loads(settings_path.read_text())
        env = data.get("env", {})
        models = []
        for label, key in [
            ("Opus", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
            ("Sonnet", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
            ("Haiku", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
        ]:
            model_id = env.get(key)
            if model_id:
                models.append({"label": label, "id": model_id})
        return models or _defaults
    except Exception:
        return _defaults


def _resolve_review_model(model: str) -> str:
    """Pick the actual model ID to use for a PR review."""
    from jarvis.config import JarvisConfig

    try:
        cfg_model = JarvisConfig.load().pr_monitor.review_model
    except Exception:
        cfg_model = ""
    available = _claude_models()
    if not cfg_model or cfg_model in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"):
        cfg_model = available[0]["id"] if available else "claude-opus-4-7"
    return model or cfg_model


def _attach_authoring_sessions(conn, subs: list[dict]) -> list[dict]:
    """Attach up to 5 authoring Claude session IDs per PR, newest first.

    A session is "authoring" when its overrides row has `pr:<repo>#<n>` in
    auto_tags (set by the PostToolUse hook on `gh pr create` or by
    `jarvis sessions backfill`). Ordered by the session event's last_active.
    """
    if not subs:
        return subs
    rows = conn.execute(
        """SELECT json_extract(e.metadata,'$.session_id') AS session_id,
                  COALESCE(json_extract(e.metadata,'$.last_message_at'), e.happened_at) AS last_active,
                  o.auto_tags AS auto_tags
           FROM events e
           JOIN claude_session_overrides o
                ON json_extract(e.metadata,'$.session_id') = o.session_id
           WHERE e.source = 'claude_sessions'
             AND o.auto_tags LIKE '%"pr:%'"""
    ).fetchall()
    by_pr: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        try:
            tags = json.loads(r["auto_tags"] or "[]")
        except json.JSONDecodeError:
            continue
        for tag in tags:
            if not tag.startswith("pr:"):
                continue
            by_pr.setdefault(tag[3:], []).append((r["last_active"] or "", r["session_id"]))
    for key in by_pr:
        by_pr[key].sort(reverse=True)
    for s in subs:
        key = f"{s['repo']}#{s['pr_number']}"
        ids = [sid for _, sid in by_pr.get(key, [])][:5]
        s["authoring_session_ids"] = ids
    return subs


def _attach_gh_accounts(conn, subs: list[dict]) -> list[dict]:
    """Mutate subs in-place to add a gh_account field based on repo_paths config."""
    repo_account_map: dict[str, str] = {}
    owner_account_map: dict[str, str] = {}
    for r in list_repo_paths(conn):
        if not r.get("gh_account"):
            continue
        full_repo = _remote_for_local_repo(str(Path(r["path"]).expanduser()))
        if full_repo:
            repo_account_map[full_repo] = r["gh_account"]
            owner = full_repo.split("/")[0]
            owner_account_map.setdefault(owner, r["gh_account"])
    for s in subs:
        owner = s["repo"].split("/")[0] if "/" in s["repo"] else s["repo"]
        s["gh_account"] = repo_account_map.get(s["repo"]) or owner_account_map.get(owner, "")
    return subs


def _markdown_to_html(markdown: str) -> str:
    """Cheap markdown → HTML conversion for summary/review rendering."""
    import re

    html = markdown
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html, flags=re.DOTALL)
    html = html.replace("\n\n", "<br><br>")
    return html


def _load_chat_history(session_id: str) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Event / timeline / search / insights / summary
# ---------------------------------------------------------------------------


def _event_to_dict(ev) -> dict:
    out = {
        "id": ev.id,
        "source": ev.source,
        "kind": ev.kind,
        "title": ev.title,
        "body": ev.body,
        "url": ev.url,
        "project": ev.project,
        "happened_at": ev.happened_at.isoformat() if ev.happened_at else None,
        "metadata": ev.metadata,
    }
    return out


@app.get("/api/timeline")
def api_timeline(
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
    sources = [
        r["source"]
        for r in conn.execute("SELECT DISTINCT source FROM events ORDER BY source").fetchall()
    ]
    projects = [
        r["project"]
        for r in conn.execute(
            "SELECT DISTINCT project FROM events WHERE project IS NOT NULL ORDER BY project"
        ).fetchall()
    ]
    conn.close()
    return {
        "events": [_event_to_dict(e) for e in page_events],
        "total": total,
        "sources": sources,
        "projects": projects,
        "has_more": len(events) == per_page * page,
        "page": page,
        "days": days,
        "source": source,
        "project": project,
    }


@app.get("/api/search")
def api_search(q: str = Query(""), limit: int = Query(30)):
    conn = get_db()
    events = search_events(conn, q, limit=limit) if q else []
    conn.close()
    return {"events": [_event_to_dict(e) for e in events], "query": q}


@app.get("/api/insights")
def api_insights(days: int = Query(30)):
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
    return ctx


@app.get("/api/summary")
def api_summary(
    kind: str = Query("standup"),
    days: int = Query(1),
    project: str | None = Query(None),
):
    """Generate a summary via Claude. Returns rendered HTML embedded in JSON."""
    from jarvis.brain import SYSTEM_PROMPTS, _call_claude, _format_events, _standup_prompt

    conn = get_db()
    events = query_events(conn, project=project, days=days, limit=200)
    conn.close()

    if not events:
        return {"html": "<p>No events found for this period.</p>"}

    if kind == "standup":
        system = _standup_prompt(days)
    elif kind in SYSTEM_PROMPTS:
        system = SYSTEM_PROMPTS[kind]
    else:
        system = SYSTEM_PROMPTS["weekly"]

    events_text = _format_events(events)
    result = _call_claude(system, events_text)
    return {"html": _markdown_to_html(result)}


@app.get("/api/suggestions")
def api_suggestions():
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
    try:
        from jarvis.ingest import ingest_all

        logs: list[str] = []
        total = ingest_all(days=days, log_collector=logs)
        logger.info("ingest total=%d", total)
        return {"ok": True, "total": total, "log": "\n".join(logs)}
    except Exception as e:
        logger.exception("ingest failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@app.get("/api/sessions")
def api_sessions(
    project: str | None = Query(None),
    repo: str | None = Query(None),
    tag: list[str] | None = Query(None),
    archived: str = Query("0"),
    q: str | None = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    from jarvis.sessions_tags import effective_tags, get_overrides_map

    conn = get_db()
    sessions = list_sessions(conn, project=project, limit=limit)

    where = ["source='claude_sessions'"]
    params: list = []
    if repo:
        where.append("project = ?")
        params.append(repo)
    rows = conn.execute(
        f"""SELECT title, happened_at, project,
                   json_extract(metadata,'$.session_id') as session_id,
                   json_extract(metadata,'$.branch') as branch,
                   json_extract(metadata,'$.cwd') as cwd,
                   json_extract(metadata,'$.turns') as turns,
                   COALESCE(json_extract(metadata,'$.last_message_at'), happened_at) as last_active
            FROM events WHERE {" AND ".join(where)}
            ORDER BY last_active DESC""",
        params,
    ).fetchall()

    overrides = get_overrides_map(conn)
    all_projects = sorted({r["project"] for r in rows if r["project"]})

    wanted_tags = set(tag or [])
    needle = (q or "").strip().lower()

    out: list[dict] = []
    seen_sessions: set[str] = set()
    for r in rows:
        sid = r["session_id"]
        if sid:
            if sid in seen_sessions:
                continue
            seen_sessions.add(sid)
        ov = overrides.get(sid or "") or {}
        is_archived = bool(ov.get("archived"))
        if archived == "0" and is_archived:
            continue
        if archived == "1" and not is_archived:
            continue
        tags = effective_tags(ov) if ov else []
        # inject repo/jarvis fallback tags when there's no overrides row yet
        if not ov:
            if r["project"]:
                tags.append(f"repo:{r['project']}")
            if r["project"] == "jarvis" or (r["cwd"] and "/jarvis" in r["cwd"]):
                tags.append("jarvis-involved")
        if wanted_tags and not wanted_tags.issubset(set(tags)):
            continue
        display_title = ov.get("display_title") or r["title"]
        if needle:
            hay = f"{display_title} {' '.join(tags)}".lower()
            if needle not in hay:
                continue
        import json as _json

        pr_links = ov.get("pr_links")
        if isinstance(pr_links, str):
            try:
                pr_links = _json.loads(pr_links)
            except Exception:
                pr_links = []
        out.append(
            {
                "session_id": sid,
                "title": r["title"],
                "display_title": display_title,
                "happened_at": r["happened_at"],
                "last_active": r["last_active"],
                "branch": r["branch"],
                "cwd": r["cwd"],
                "project": r["project"],
                "turns": r["turns"],
                "tags": tags,
                "archived": is_archived,
                "pr_links": pr_links or [],
            }
        )

    # Enrich pr_links with the correct gh account + full URL so the UI can
    # route clicks through /api/open-url (which opens the matching Firefox
    # profile). Without this, opening a PR from a work repo would pollute
    # the default profile's history and fail to auth.
    if out:
        repo_account_map: dict[str, str] = {}
        owner_account_map: dict[str, str] = {}
        for r in list_repo_paths(conn):
            if not r.get("gh_account"):
                continue
            full_repo = _remote_for_local_repo(str(Path(r["path"]).expanduser()))
            if full_repo:
                repo_account_map[full_repo] = r["gh_account"]
                owner = full_repo.split("/")[0]
                owner_account_map.setdefault(owner, r["gh_account"])
        for item in out:
            enriched = []
            for link in item["pr_links"]:
                repo = link.get("repo") or ""
                number = link.get("number")
                owner = repo.split("/")[0] if "/" in repo else repo
                enriched.append(
                    {
                        "repo": repo,
                        "number": number,
                        "gh_account": repo_account_map.get(repo)
                        or owner_account_map.get(owner)
                        or None,
                        "pr_url": f"https://github.com/{repo}/pull/{number}",
                    }
                )
            item["pr_links"] = enriched

    # collect all tags present in effective sets for filter UI
    all_tags_set: set[str] = set()
    for item in out:
        all_tags_set.update(item["tags"])

    total = len(out)
    paged = out[offset : offset + limit]
    conn.close()
    return {
        "sessions": [dict(s) for s in sessions],
        "claude_sessions": paged,
        "total": total,
        "projects": all_projects,
        "all_tags": sorted(all_tags_set),
    }


@app.patch("/api/claude-sessions/{session_id}")
def api_claude_session_patch(session_id: str, body: dict = Body(...)):
    from jarvis.sessions_tags import apply_patch, effective_tags

    conn = get_db()
    row = apply_patch(
        conn,
        session_id,
        display_title=body.get("display_title"),
        clear_display_title=body.get("clear_display_title", False),
        archived=body.get("archived"),
        add_tags=body.get("add_tags"),
        remove_tags=body.get("remove_tags"),
    )
    conn.close()
    return {
        "session_id": session_id,
        "display_title": row.get("display_title"),
        "archived": bool(row.get("archived")),
        "tags": effective_tags(row),
    }


@app.post("/api/claude-sessions/recorrelate")
def api_claude_session_recorrelate():
    from jarvis.sessions_tags import correlate_claude_sessions

    updated = correlate_claude_sessions()
    return {"updated": updated}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@app.get("/api/chat/session/{session_id}")
def api_chat_session(session_id: str, autostart: int = Query(1)):
    """Fetch metadata for a chat session: history, autostart prompt, preview title."""
    history_preview = ""
    autostart_prompt = ""
    autostart_model = ""
    conn = get_db()
    row = conn.execute(
        "SELECT title FROM events WHERE json_extract(metadata,'$.session_id')=? LIMIT 1",
        (session_id,),
    ).fetchone()
    if row:
        history_preview = row["title"]
    if autostart:
        raw = kv_get(conn, f"review_prompt:{session_id}")
        if raw:
            data = json.loads(raw)
            autostart_prompt = data.get("prompt", "")
            autostart_model = data.get("model", "")
            # one-shot: consume it
            conn.execute("DELETE FROM kv WHERE key=?", (f"review_prompt:{session_id}",))
            conn.commit()
    conn.close()
    history = _load_chat_history(session_id)
    return {
        "session_id": session_id,
        "history_preview": history_preview,
        "history": history,
        "autostart_prompt": autostart_prompt,
        "autostart_model": autostart_model,
    }


@app.post("/api/chat/stream")
def api_chat_stream(
    message: str = Form(...),
    session_id: str = Form(""),
    model: str = Form(""),
):
    new_id = session_id or str(uuid_mod.uuid4())
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--bare", "--tools", ""]
    if model:
        cmd += ["--model", model]
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
        assert proc.stdin is not None
        proc.stdin.write(message)
        proc.stdin.close()
        finished = False
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                t = obj.get("type")
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
        assert proc.stderr is not None
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
# Upcoming (Focus)
# ---------------------------------------------------------------------------


@app.get("/api/upcoming")
def api_upcoming():
    import zoneinfo as _zi

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

    meetings: list[dict] = []
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

    top_prs = subscriptions_watching(conn)[:5]
    _attach_gh_accounts(conn, top_prs)
    available_models = _claude_models()
    review_model = _resolve_review_model("")

    from jarvis.memory import _group_sprint_tickets, _recent_nonsprint_jira

    active_sprints = _group_sprint_tickets(conn)
    recent_jira = _recent_nonsprint_jira(conn)
    conn.close()

    return {
        "today": _today.isoformat(),
        "today_label": _today.strftime("%A, %B %-d"),
        "meetings": meetings,
        "top_prs": top_prs,
        "active_sprints": active_sprints,
        "recent_jira": recent_jira,
        "review_model": review_model,
        "available_models": available_models,
    }


# ---------------------------------------------------------------------------
# PRs
# ---------------------------------------------------------------------------


@app.get("/api/prs")
def api_prs(
    repo: str | None = Query(None),
    author: str | None = Query(None),
):
    conn = get_db()
    watching = subscriptions_watching(conn)
    pending = subscriptions_pending(conn)
    later = subscriptions_later(conn)
    dismissed = subscriptions_dismissed(conn)

    _attach_gh_accounts(conn, watching)
    _attach_gh_accounts(conn, pending)
    _attach_gh_accounts(conn, later)
    _attach_gh_accounts(conn, dismissed)
    _attach_authoring_sessions(conn, watching)
    _attach_authoring_sessions(conn, pending)
    _attach_authoring_sessions(conn, later)
    _attach_authoring_sessions(conn, dismissed)

    all_repos = sorted({s["repo"] for s in watching})
    all_authors = sorted({s["author"] for s in watching if s.get("author")})

    if repo:
        watching = [s for s in watching if s["repo"] == repo]
    if author:
        watching = [s for s in watching if s.get("author") == author]

    last_checked = kv_get(conn, "last_pr_check_at")
    conn.close()

    return {
        "pending": pending,
        "watching": watching,
        "later": later,
        "dismissed": dismissed,
        "all_repos": all_repos,
        "all_authors": all_authors,
        "last_checked": last_checked,
        "review_model": _resolve_review_model(""),
        "available_models": _claude_models(),
        "filter_repo": repo or "",
        "filter_author": author or "",
    }


@app.get("/api/prs/pending-count")
def api_prs_pending_count():
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM pr_subscriptions WHERE watch_state='pending' AND state='open'"
    ).fetchone()[0]
    conn.close()
    return {"count": count}


def _fetch_subscription(conn, repo: str, pr_number: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM pr_subscriptions WHERE repo=? AND pr_number=?", (repo, pr_number)
    ).fetchone()
    return dict(row) if row else None


@app.post("/api/prs/{repo_encoded}/{pr_number}/watch")
def api_prs_watch(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    set_pr_watch_state(conn, repo, pr_number, "watching")
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    logger.info("pr.watch repo=%s pr=%s", repo, pr_number)
    return {"ok": True, "subscription": sub}


@app.post("/api/prs/{repo_encoded}/{pr_number}/dismiss")
def api_prs_dismiss(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    set_pr_watch_state(conn, repo, pr_number, "dismissed")
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    logger.info("pr.dismiss repo=%s pr=%s", repo, pr_number)
    return {"ok": True, "subscription": sub}


@app.post("/api/prs/{repo_encoded}/{pr_number}/later")
def api_prs_later(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    set_pr_watch_state(conn, repo, pr_number, "later")
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    logger.info("pr.later repo=%s pr=%s", repo, pr_number)
    return {"ok": True, "subscription": sub}


@app.post("/api/prs/{repo_encoded}/{pr_number}/restore")
def api_prs_restore(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    set_pr_watch_state(conn, repo, pr_number, "pending")
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    logger.info("pr.restore repo=%s pr=%s", repo, pr_number)
    return {"ok": True, "subscription": sub}


@app.post("/api/prs/{repo_encoded}/{pr_number}/priority")
def api_prs_priority(repo_encoded: str, pr_number: int, priority: int = Form(0)):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    set_pr_priority(conn, repo, pr_number, priority)
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    logger.info("pr.priority repo=%s pr=%s val=%d", repo, pr_number, priority)
    return {"ok": True, "subscription": sub}


@app.delete("/api/prs/{repo_encoded}/{pr_number}")
def api_prs_unsubscribe(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    _subscription_delete(conn, repo, pr_number)
    conn.close()
    logger.info("pr.unsubscribe repo=%s pr=%s", repo, pr_number)
    return {"ok": True}


@app.get("/api/prs/{repo_encoded}/{pr_number}/refresh")
def api_pr_refresh(repo_encoded: str, pr_number: int):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    refresh_one(conn, {"repo": repo, "pr_number": pr_number})
    sub = _fetch_subscription(conn, repo, pr_number)
    conn.close()
    return {"ok": True, "subscription": sub}


@app.post("/api/prs/refresh-all")
def api_prs_refresh_all():
    conn = get_db()
    subs = _subscriptions_active(conn)
    updated = sum(1 for sub in subs if refresh_one(conn, sub))
    kv_set(conn, "last_pr_check_at", datetime.now(UTC).isoformat())
    conn.close()
    logger.info("refresh_all updated=%d", updated)
    return {"ok": True, "updated": updated}


@app.post("/api/prs/refresh-running")
def api_prs_refresh_running():
    """Refresh only the watched PRs whose cached CI status is still "running"."""
    conn = get_db()
    targets = [s for s in subscriptions_watching(conn) if s.get("ci_status") == "running"]
    refreshed = 0
    still_running = 0
    for sub in targets:
        if refresh_one(conn, sub):
            refreshed += 1
            reloaded = _fetch_subscription(conn, sub["repo"], sub["pr_number"])
            if reloaded and reloaded.get("ci_status") == "running":
                still_running += 1
    conn.close()
    logger.info("refresh_running refreshed=%d still_running=%d", refreshed, still_running)
    return {"ok": True, "refreshed": refreshed, "still_running": still_running}


@app.post("/api/prs/discover")
def api_prs_discover():
    from jarvis.config import JarvisConfig

    config = JarvisConfig.load()
    conn = get_db()
    prs: list[dict] = []
    seen: set[str] = set()

    repo_accounts: list[tuple[str, str | None]] = [(r, None) for r in config.github.repos or []]
    for repo, acct in _repos_from_db(conn):
        if not any(r == repo for r, _ in repo_accounts):
            repo_accounts.append((repo, acct))
    conn.close()
    for r in _repos_from_local_paths(config):
        if not any(repo == r for repo, _ in repo_accounts):
            repo_accounts.append((r, None))

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

    gh_accounts_set = set(_gh_accounts())
    conn2 = get_db()
    for pr in prs:
        author_login = (
            pr.get("author", {}).get("login") if isinstance(pr.get("author"), dict) else None
        )
        gh_username = None
        pr_repo = pr["repo"]
        owner = pr_repo.split("/")[0] if "/" in pr_repo else ""
        for acct in gh_accounts_set:
            if acct == author_login or acct == owner:
                gh_username = acct
                break
        _subscription_upsert(conn2, pr["repo"], pr["number"], pr, gh_username=gh_username)
        ci = _parse_ci_status(pr)
        rd = pr.get("reviewDecision") or ""
        pr_state = (pr.get("state") or "").lower()
        update_pr_cache(conn2, pr["repo"], pr["number"], ci, rd, state=pr_state or None)
        if pr_state in ("merged", "closed"):
            set_pr_watch_state(conn2, pr["repo"], pr["number"], "dismissed")
    conn2.close()

    discovered = len(prs)
    logger.info("discover found=%d", discovered)
    return {"ok": True, "discovered": discovered, "total": discovered}


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
    return {"ok": True}


@app.post("/api/prs/{repo_encoded}/{pr_number}/review")
def api_prs_review(repo_encoded: str, pr_number: int, model: str = Form("")):
    """Start a Claude review chat — returns the session_id and redirect URL."""
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    sub = _fetch_subscription(conn, repo, pr_number)
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="PR not found")

    chosen_model = _resolve_review_model(model)
    existing_session = sub.get("chat_session_id")
    if existing_session:
        conn.close()
        return {"session_id": existing_session, "redirect": f"/chat?session={existing_session}"}

    token = _token_for_repo(conn, repo)
    env = {**os.environ, "GH_TOKEN": token} if token else None
    pr_info = (
        _gh(
            "pr",
            "view",
            str(pr_number),
            "--json",
            "title,body,author,reviews,reviewDecision,statusCheckRollup",
            repo=repo,
            env=env,
        )
        or {}
    )
    diff_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
        timeout=30,
        env=env or os.environ,
    )
    diff_text = diff_result.stdout[:20000] if diff_result.returncode == 0 else "(diff unavailable)"

    prompt_parts = [
        f"Please review this pull request:\n\n**{pr_info.get('title', sub.get('title', ''))}**",
        f"Repo: {repo} | PR #{pr_number}",
    ]
    if pr_info.get("body"):
        prompt_parts.append(f"\n**Description:**\n{pr_info['body']}")
    ci = sub.get("ci_status") or "unknown"
    rd = sub.get("review_decision") or "pending"
    prompt_parts.append(f"\n**CI:** {ci} | **Reviews:** {rd}")
    prompt_parts.append(f"\n**Diff:**\n```diff\n{diff_text}\n```")
    prompt_parts.append(
        "\nPlease give a thorough code review: correctness, potential bugs, design, test coverage, and any suggestions."
    )
    prompt = "\n".join(prompt_parts)

    new_session_id = str(uuid_mod.uuid4())
    set_pr_chat_session(conn, repo, pr_number, new_session_id)
    # Tag review sessions as pr-review:<repo>#<n> so the Sessions page can
    # segregate them from regular conversations and the PR card can jump
    # straight to the review later.
    from jarvis.sessions_tags import apply_patch

    apply_patch(conn, new_session_id, add_tags=[f"pr-review:{repo}#{pr_number}"])
    kv_set(
        conn,
        f"review_prompt:{new_session_id}",
        json.dumps({"prompt": prompt, "model": chosen_model}),
    )
    conn.close()
    logger.info(
        "pr.review repo=%s pr=%s model=%s session=%s", repo, pr_number, chosen_model, new_session_id
    )
    return {
        "session_id": new_session_id,
        "redirect": f"/chat?session={new_session_id}&autostart=1",
    }


@app.post("/api/prs/{repo_encoded}/{pr_number}/rereview")
def api_prs_rereview(repo_encoded: str, pr_number: int, model: str = Form("")):
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    sub = _fetch_subscription(conn, repo, pr_number)
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="PR not found")

    existing_session = sub.get("chat_session_id")
    if not existing_session:
        conn.close()
        return api_prs_review(repo_encoded, pr_number, model)

    chosen_model = _resolve_review_model(model)
    token = _token_for_repo(conn, repo)
    env = {**os.environ, "GH_TOKEN": token} if token else None
    diff_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
        timeout=30,
        env=env or os.environ,
    )
    diff_text = diff_result.stdout[:20000] if diff_result.returncode == 0 else "(diff unavailable)"

    prompt = (
        "Please re-review this PR with the latest diff. "
        "Focus on any new changes since the last review and update your assessment.\n\n"
        f"**Latest diff:**\n```diff\n{diff_text}\n```"
    )

    kv_set(
        conn,
        f"review_prompt:{existing_session}",
        json.dumps({"prompt": prompt, "model": chosen_model}),
    )
    conn.close()
    logger.info(
        "pr.rereview repo=%s pr=%s model=%s session=%s",
        repo,
        pr_number,
        chosen_model,
        existing_session,
    )
    return {
        "session_id": existing_session,
        "redirect": f"/chat?session={existing_session}&autostart=1",
    }


@app.get("/api/prs/{repo_encoded}/{pr_number}/detail")
def api_pr_detail(repo_encoded: str, pr_number: int):
    """Return PR detail as structured JSON."""
    repo = _repo_decode(repo_encoded)
    conn = get_db()
    token = _token_for_repo(conn, repo)
    conn.close()
    env = {**os.environ, "GH_TOKEN": token} if token else None

    pr = _gh(
        "pr",
        "view",
        str(pr_number),
        "--json",
        (
            "title,body,number,headRefName,url,author,"
            "reviewDecision,statusCheckRollup,changedFiles,additions,deletions,reviews,comments"
        ),
        repo=repo,
        env=env,
    )
    if pr is None:
        raise HTTPException(status_code=404, detail="Could not fetch PR details")

    threads_data = _gh("api", f"repos/{repo}/pulls/{pr_number}/comments", env=env) or []
    threads: dict[str, list[dict]] = {}
    for c in threads_data if isinstance(threads_data, list) else []:
        key = c.get("path", "") + ":" + str(c.get("original_position", ""))
        threads.setdefault(key, []).append(c)

    thread_list = [
        {
            "path": comments[0].get("path", ""),
            "comments": [
                {
                    "id": c.get("id"),
                    "author": c.get("user", {}).get("login", ""),
                    "body": c.get("body", ""),
                }
                for c in comments
            ],
        }
        for comments in threads.values()
    ]

    return {
        "title": pr.get("title", ""),
        "body": pr.get("body") or "",
        "number": pr.get("number"),
        "branch": pr.get("headRefName", ""),
        "url": pr.get("url"),
        "changed_files": pr.get("changedFiles", 0),
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "ci_status": _parse_ci_status(pr),
        "review_decision": pr.get("reviewDecision"),
        "checks": [
            {
                "name": chk.get("name") or chk.get("context", ""),
                "status": chk.get("conclusion") or chk.get("status", ""),
                "url": chk.get("detailsUrl") or chk.get("targetUrl"),
            }
            for chk in pr.get("statusCheckRollup") or []
        ],
        "threads": thread_list,
    }


@app.post("/api/prs/{repo_encoded}/{pr_number}/reply/{comment_id}")
def api_pr_reply(repo_encoded: str, pr_number: int, comment_id: int, body: str = Form(...)):
    repo = _repo_decode(repo_encoded)
    subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/comments/{comment_id}/replies", "-f", f"body={body}"],
        capture_output=True,
        timeout=15,
    )
    return {"ok": True, "body": body}


# ---------------------------------------------------------------------------
# Open URL + settings
# ---------------------------------------------------------------------------


@app.post("/api/open-url")
def api_open_url(
    url: str = Form(...),
    gh_account: str = Form(""),
    jira_host: str = Form(""),
):
    conn = get_db()
    profile_path = _profile_for_account(conn, gh_account or None, jira_host=jira_host or None)
    conn.close()
    if _firefox_installed() and profile_path:
        base = Path.home() / "Library/Application Support/Firefox"
        abs_profile = base / profile_path
        firefox_bin = "/Applications/Firefox.app/Contents/MacOS/firefox"
        subprocess.Popen(
            [firefox_bin, "--no-remote", "--profile", str(abs_profile), "--new-window", url]
        )
    else:
        subprocess.Popen(["open", url])
    logger.info("open_url gh_account=%s jira_host=%s url=%.80s", gh_account, jira_host, url)
    return {"ok": True}


@app.get("/api/settings/repo-paths")
def api_settings_repo_paths_get():
    conn = get_db()
    rows = list_repo_paths(conn)
    for r in rows:
        r["remote_repo"] = _remote_for_local_repo(str(Path(r["path"]).expanduser()))
    accounts = _gh_accounts()
    conn.close()
    return {"paths": rows, "available_accounts": accounts}


@app.post("/api/settings/repo-paths")
def api_settings_repo_paths_add(path: str = Form(...)):
    p = path.strip()
    conn = get_db()
    row_id = add_repo_path(conn, p)
    repo = _remote_for_local_repo(str(Path(p).expanduser()))
    if repo:
        account = _detect_account_for_repo(repo)
        if account:
            set_repo_path_account(conn, row_id, account)
    conn.close()
    return api_settings_repo_paths_get()


@app.post("/api/settings/repo-paths/browse")
def api_settings_repo_paths_browse():
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
            return api_settings_repo_paths_get()
        chosen = result.stdout.strip().rstrip("/")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folder picker error: {e}") from e

    chosen_path = Path(chosen)
    candidates: list[str] = []
    if (chosen_path / ".git").exists():
        candidates = [chosen]
    else:
        for sub in sorted(chosen_path.iterdir()):
            if sub.is_dir() and (sub / ".git").exists():
                candidates.append(str(sub))

    if not candidates:
        raise HTTPException(status_code=400, detail="No git repos found in that folder")

    conn = get_db()
    for p in candidates:
        row_id = add_repo_path(conn, p)
        repo = _remote_for_local_repo(p)
        if repo:
            account = _detect_account_for_repo(repo)
            if account:
                set_repo_path_account(conn, row_id, account)
    conn.close()
    return api_settings_repo_paths_get()


@app.delete("/api/settings/repo-paths/{path_id}")
def api_settings_repo_paths_delete(path_id: str):
    conn = get_db()
    delete_repo_path(conn, path_id)
    conn.close()
    return api_settings_repo_paths_get()


@app.post("/api/settings/repo-paths/{path_id}/account")
def api_settings_repo_paths_set_account(path_id: str, gh_account: str = Form(...)):
    conn = get_db()
    set_repo_path_account(conn, path_id, gh_account or None)
    conn.close()
    return api_settings_repo_paths_get()


@app.post("/api/settings/repo-paths/{path_id}/toggle")
def api_settings_repo_paths_toggle(path_id: str):
    conn = get_db()
    row = conn.execute("SELECT enabled FROM repo_paths WHERE id=?", (path_id,)).fetchone()
    if row:
        set_repo_path_enabled(conn, path_id, not row["enabled"])
    conn.close()
    return api_settings_repo_paths_get()


@app.get("/api/settings/browser-profiles")
def api_settings_browser_profiles():
    if not _firefox_installed():
        return {"installed": False, "profiles": [], "accounts": {}}
    profiles = _firefox_profiles()
    accounts = _gh_accounts()
    conn = get_db()
    account_map = {acct: kv_get(conn, f"browser_profile:{acct}") or "" for acct in accounts}
    conn.close()
    return {"installed": True, "profiles": profiles, "accounts": account_map}


@app.post("/api/settings/browser-profile/{account}")
def api_settings_browser_profile_set(account: str, profile: str = Form("")):
    conn = get_db()
    kv_set(conn, f"browser_profile:{account}", profile)
    conn.close()
    return api_settings_browser_profiles()


@app.get("/api/settings/gcal-profiles")
def api_settings_gcal_profiles():
    """Map Google Calendar account name → Firefox profile path.

    Supersedes the older gcal_gh_account hop — meeting/calendar links now
    open directly in the mapped profile without needing a gh account
    intermediary. Stored as `browser_profile:<cal_account>` in kv, which is
    the same prefix `_profile_for_account` already checks at step 1.
    """
    from jarvis.config import JarvisConfig

    try:
        gcal_accounts = [a.name for a in JarvisConfig.load().gcal.accounts]
    except Exception:
        gcal_accounts = []
    conn = get_db()
    mapping = {cal: kv_get(conn, f"browser_profile:{cal}") or "" for cal in gcal_accounts}
    conn.close()
    profiles = _firefox_profiles() if _firefox_installed() else []
    return {
        "installed": _firefox_installed(),
        "gcal_accounts": gcal_accounts,
        "mapping": mapping,
        "profiles": profiles,
    }


@app.post("/api/settings/gcal-profile/{cal_account}")
def api_settings_gcal_profile_set(cal_account: str, profile: str = Form("")):
    conn = get_db()
    kv_set(conn, f"browser_profile:{cal_account}", profile)
    conn.close()
    return api_settings_gcal_profiles()


@app.get("/api/settings/jira-profiles")
def api_settings_jira_profiles():
    """Map Jira hosts → Firefox profiles for URL routing."""
    from jarvis.db import list_jira_board_subs

    conn = get_db()
    hosts = sorted({sub["host"] for sub in list_jira_board_subs(conn)})
    mapping = {h: kv_get(conn, f"jira_profile:{h}") or "" for h in hosts}
    conn.close()
    profiles = _firefox_profiles() if _firefox_installed() else []
    return {
        "installed": _firefox_installed(),
        "hosts": hosts,
        "mapping": mapping,
        "profiles": profiles,
    }


@app.post("/api/settings/jira-profile/{host}")
def api_settings_jira_profile_set(host: str, profile: str = Form("")):
    conn = get_db()
    kv_set(conn, f"jira_profile:{host}", profile)
    conn.close()
    return api_settings_jira_profiles()


# ---------------------------------------------------------------------------
# SPA shell — serve index.html for any non-/api route that doesn't match
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def spa_root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse(
        "<h1>Frontend not built</h1><p>Run <code>cd frontend && npm run build</code>.</p>"
    )


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_catch_all(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse(
        "<h1>Frontend not built</h1><p>Run <code>cd frontend && npm run build</code>.</p>"
    )
