from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
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
    conn.close()

    return templates.TemplateResponse(
        request,
        "sessions.html",
        {
            "sessions": sessions,
            "project": project,
        },
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
