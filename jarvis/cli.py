from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jarvis.config import CONFIG_PATH, DB_PATH, JARVIS_HOME, JarvisConfig, ensure_jarvis_home
from jarvis.db import event_count, get_db, init_db, query_events, search_events

app = typer.Typer(help="Jarvis — Personal engineering assistant", invoke_without_command=True)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        import jarvis

        print(jarvis.__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Start Jarvis: menu bar icon + web dashboard (non-blocking)."""
    if ctx.invoked_subcommand is not None:
        return
    from jarvis.launcher import launch

    launch()


def _track_and_suggest(command: str, t0: float, exit_code: int) -> None:
    """Record CLI usage and show top pending suggestion. Best-effort — never raises."""
    try:
        from jarvis.activity import record_cli
        from jarvis.suggestions import evaluate_all, get_pending

        conn = get_db()
        duration_ms = int((time.monotonic() - t0) * 1000)
        record_cli(conn, command, sys.argv[1:], None, duration_ms, exit_code)
        evaluate_all(conn)
        pending = get_pending(conn)
        conn.close()
        if pending:
            top = pending[0]
            console.print(
                Panel(
                    f"[bold]{top.message}[/bold]\n[dim]Run:[/dim] [cyan]{top.action}[/cyan]"
                    f"\n[dim]Dismiss:[/dim] jarvis suggest dismiss {top.rule_id}",
                    title="[yellow]💡 Suggestion[/yellow]",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
    except Exception:
        pass


@app.command()
def init() -> None:
    """Initialize Jarvis: create ~/.jarvis/ with config and database."""
    ensure_jarvis_home()
    init_db()
    console.print("[green]Jarvis initialized.[/green]")
    console.print(f"  Config: {CONFIG_PATH}")
    console.print(f"  Database: {DB_PATH}")
    console.print("\nEdit your config to add repos and integrations:")
    console.print(f"  [bold]{CONFIG_PATH}[/bold]")
    console.print("\nStore your GitHub token securely:")
    console.print(
        '  [bold]python -c "import keyring; '
        "keyring.set_password('jarvis', 'github_token', 'ghp_YOUR_TOKEN')\"[/bold]"
    )


@app.command()
def ingest(
    days: int = typer.Option(7, help="How many days back to fetch"),
    source: str | None = typer.Option(None, help="Only ingest from this source"),
) -> None:
    """Pull latest events from all configured integrations."""
    t0 = time.monotonic()
    ensure_jarvis_home()
    from jarvis.ingest import ingest_all

    console.print(f"[bold]Ingesting events (last {days} days)...[/bold]")
    total = ingest_all(days=days, source_filter=source)
    conn = get_db()
    total_db = event_count(conn)
    console.print(f"\n[green]Done.[/green] {total} events ingested. Total in DB: {total_db}")
    conn.close()
    _track_and_suggest("ingest", t0, 0)


@app.command()
def log(
    source: str | None = typer.Option(None, help="Filter by source (git_local, github)"),
    project: str | None = typer.Option(None, help="Filter by project name"),
    days: int = typer.Option(7, help="How many days back to show"),
    limit: int = typer.Option(30, help="Max events to show"),
) -> None:
    """Show recent activity events."""
    t0 = time.monotonic()
    conn = get_db()
    events = query_events(conn, source=source, project=project, days=days, limit=limit)
    conn.close()

    if not events:
        console.print("[yellow]No events found.[/yellow]")
        return

    table = Table(title=f"Activity Log ({len(events)} events)")
    table.add_column("Time", style="dim", width=16)
    table.add_column("Source", width=10)
    table.add_column("Kind", width=14)
    table.add_column("Project", width=16)
    table.add_column("Title", no_wrap=False)

    source_colors = {
        "git_local": "cyan",
        "github": "green",
        "jira": "blue",
        "gcal": "magenta",
    }

    for e in events:
        time_str = e.happened_at.strftime("%m-%d %H:%M")
        src_color = source_colors.get(e.source, "white")
        table.add_row(
            time_str,
            f"[{src_color}]{e.source}[/{src_color}]",
            e.kind,
            e.project or "-",
            e.title[:80],
        )

    console.print(table)
    _track_and_suggest("log", t0, 0)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(20, help="Max results"),
) -> None:
    """Full-text search across all events."""
    conn = get_db()
    events = search_events(conn, query, limit=limit)
    conn.close()

    if not events:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return

    table = Table(title=f"Search: '{query}' ({len(events)} results)")
    table.add_column("Time", style="dim", width=16)
    table.add_column("Source", width=10)
    table.add_column("Project", width=16)
    table.add_column("Title", no_wrap=False)

    for e in events:
        time_str = e.happened_at.strftime("%m-%d %H:%M")
        table.add_row(time_str, e.source, e.project or "-", e.title[:80])

    console.print(table)


@app.command()
def standup(
    days: int = typer.Option(1, help="How many days back to include"),
    project: str | None = typer.Option(None, help="Scope to a specific project"),
) -> None:
    """Generate standup notes from recent activity using Claude."""
    from jarvis.workflows.standup import generate_standup

    console.print("[bold]Generating standup...[/bold]\n")
    try:
        result = generate_standup(days=days, project=project)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    from rich.markdown import Markdown

    console.print(Markdown(result))


@app.command()
def weekly(
    project: str | None = typer.Option(None, help="Scope to a specific project"),
) -> None:
    """Generate a weekly summary using Claude."""
    from jarvis.workflows.weekly_summary import generate_weekly

    console.print("[bold]Generating weekly summary...[/bold]\n")
    try:
        result = generate_weekly(project=project)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    from rich.markdown import Markdown

    console.print(Markdown(result))


@app.command()
def ask(
    query: str = typer.Argument(..., help="Question about your work"),
    days: int = typer.Option(14, help="How many days of context to include"),
) -> None:
    """Ask a natural language question about your work history."""
    from rich.markdown import Markdown

    from jarvis.brain import answer_query

    conn = get_db()
    events = query_events(conn, days=days, limit=200)
    conn.close()

    if not events:
        console.print("[yellow]No events found to answer from.[/yellow]")
        return

    console.print("[bold]Thinking...[/bold]\n")
    try:
        result = answer_query(query, events)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(Markdown(result))


@app.command()
def context(
    project: str | None = typer.Option(None, help="Scope to a specific project"),
    days: int = typer.Option(2, help="How many days of context to include"),
    raw: bool = typer.Option(False, "--raw", help="Output raw markdown (for piping/hooks)"),
) -> None:
    """Show a context briefing — what you've been working on recently."""
    from rich.markdown import Markdown

    from jarvis.memory import generate_context

    if not raw:
        console.print("[bold]Generating context briefing...[/bold]\n")
    try:
        result = generate_context(project=project, days=days)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if raw:
        print(result)
    else:
        console.print(Markdown(result))


# --- Session subcommands ---

session_app = typer.Typer(help="Manage session memory")
app.add_typer(session_app, name="session")


@session_app.command("save")
def session_save(
    project: str | None = typer.Option(None, help="Project name"),
    days: int = typer.Option(1, help="How many days to summarize"),
) -> None:
    """Capture current work as a session snapshot."""
    from jarvis.memory import capture_session

    console.print("[bold]Capturing session...[/bold]\n")
    try:
        summary = capture_session(project=project, days=days)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    from rich.markdown import Markdown

    console.print(Markdown(summary))
    console.print("\n[green]Session saved.[/green]")


@session_app.command("list")
def session_list(
    project: str | None = typer.Option(None, help="Filter by project"),
    limit: int = typer.Option(10, help="Max sessions to show"),
) -> None:
    """List recent session snapshots."""
    from jarvis.db import list_sessions

    conn = get_db()
    sessions = list_sessions(conn, project=project, limit=limit)
    conn.close()

    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(title=f"Sessions ({len(sessions)})")
    table.add_column("Time", style="dim", width=16)
    table.add_column("Project", width=16)
    table.add_column("Context", no_wrap=False)

    for s in sessions:
        ts = s["started_at"][:16]
        # Show first 120 chars of context
        ctx = s["context"][:120] + ("..." if len(s["context"]) > 120 else "")
        table.add_row(ts, s.get("project") or "-", ctx)

    console.print(table)


@app.command()
def remember(
    note: str = typer.Argument(..., help="Note to remember"),
    project: str | None = typer.Option(None, help="Associate with a project"),
) -> None:
    """Manually record a note or context for future reference."""
    from jarvis.memory import remember_note

    remember_note(note, project=project)
    console.print(f"[green]Noted.[/green] {note[:80]}")


@app.command()
def prep(
    topic: str = typer.Argument(..., help="Meeting name or topic to prepare for"),
    days: int = typer.Option(14, help="How many days of context to search"),
) -> None:
    """Prepare a briefing for a meeting or topic."""
    from rich.markdown import Markdown

    from jarvis.brain import _call_claude, _format_events

    conn = get_db()
    # Search for events related to the topic
    events = search_events(conn, topic, limit=30)
    # Also get recent events for broader context
    recent = query_events(conn, days=days, limit=50)
    conn.close()

    all_events_text = ""
    if events:
        all_events_text += "## Events matching topic\n" + _format_events(events)
    if recent:
        all_events_text += "\n\n## Recent activity\n" + _format_events(recent)

    if not all_events_text:
        console.print("[yellow]No events found to prepare from.[/yellow]")
        return

    console.print(f"[bold]Preparing briefing for '{topic}'...[/bold]\n")
    try:
        result = _call_claude(
            f"You are preparing a briefing for a meeting or discussion about: {topic}\n\n"
            "Given the work events below, produce a concise briefing with:\n"
            "**Context:** What's the current state of this topic?\n"
            "**Recent Activity:** What was done recently related to this?\n"
            "**Key People:** Who's involved?\n"
            "**Talking Points:** What should be discussed?\n\n"
            "Be concise and specific. Use ticket/PR numbers.",
            all_events_text,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(Markdown(result))


@app.command()
def status() -> None:
    """Show Jarvis status: config, DB stats, integration health."""
    config = JarvisConfig.load()
    conn = get_db()
    total = event_count(conn)
    conn.close()

    console.print("[bold]Jarvis Status[/bold]\n")
    console.print(f"  Config: {CONFIG_PATH}")
    console.print(f"  Database: {DB_PATH}")
    console.print(f"  Events in DB: {total}\n")

    console.print("[bold]Integrations:[/bold]")
    if config.git_local.repo_paths:
        console.print(f"  git_local: {len(config.git_local.repo_paths)} repos configured")
    else:
        console.print("  git_local: [yellow]no repos configured[/yellow]")

    if config.github.username and config.github.repos:
        console.print(f"  github: {config.github.username} — {len(config.github.repos)} repos")
    else:
        console.print("  github: [yellow]not configured[/yellow]")

    if config.jira.enabled:
        keys = config.jira.project_keys
        if keys:
            console.print(f"  jira: enabled (via jira-cli) — {len(keys)} project(s)")
        else:
            console.print("  jira: enabled (via jira-cli, default project)")
    else:
        console.print("  jira: [yellow]disabled[/yellow]")

    if config.gcal.calendar_id:
        console.print(f"  gcal: calendar '{config.gcal.calendar_id}'")
    else:
        console.print("  gcal: [yellow]not configured[/yellow]")

    if config.kafka.enabled:
        console.print("  kafka: enabled (shell history parsing for hfkcat/kcat)")
    else:
        console.print("  kafka: [yellow]disabled[/yellow]")


@app.command()
def insights(
    days: int = typer.Option(30, help="How many days of data to analyze"),
) -> None:
    """Show work pattern insights — peak hours, top collaborators, context switching."""
    from rich.markdown import Markdown

    from jarvis.patterns import generate_insights

    conn = get_db()
    result = generate_insights(conn, days=days)
    conn.close()
    console.print(Markdown(result))


@app.command()
def people(
    resolve: bool = typer.Option(False, "--resolve", help="Run entity resolution first"),
) -> None:
    """List people across all sources (GitHub, Jira, Calendar, Git)."""
    from jarvis.resolver import list_people, resolve_entities

    conn = get_db()
    if resolve:
        merges = resolve_entities(conn)
        if merges:
            console.print(f"[blue]Resolved {merges} duplicate entities.[/blue]\n")

    people_list = list_people(conn)
    conn.close()

    if not people_list:
        console.print("[yellow]No people found. Run `jarvis ingest` first.[/yellow]")
        return

    table = Table(title=f"People ({len(people_list)})")
    table.add_column("Name", no_wrap=False)
    table.add_column("Aliases", no_wrap=False)
    table.add_column("Events", justify="right", width=8)

    for p in people_list:
        aliases = ", ".join(p["aliases"][:3])
        if len(p["aliases"]) > 3:
            aliases += f" (+{len(p['aliases']) - 3})"
        table.add_row(p["name"], aliases or "-", str(p["event_count"]))

    console.print(table)


# --- Suggest subcommands ---

suggest_app = typer.Typer(help="Manage proactive suggestions")
app.add_typer(suggest_app, name="suggest")


@suggest_app.callback(invoke_without_command=True)
def suggest_default(ctx: typer.Context) -> None:
    """Show pending suggestions."""
    if ctx.invoked_subcommand is not None:
        return
    from jarvis.suggestions import evaluate_all, get_pending

    conn = get_db()
    evaluate_all(conn)
    pending = get_pending(conn)
    conn.close()

    if not pending:
        console.print("[green]No suggestions right now.[/green]")
        return

    table = Table(title=f"Suggestions ({len(pending)})")
    table.add_column("ID", style="dim", width=20)
    table.add_column("Priority", justify="right", width=8)
    table.add_column("Message", no_wrap=False)
    table.add_column("Action", style="cyan", no_wrap=False)

    for s in pending:
        table.add_row(s.rule_id, str(s.priority), s.message, s.action)

    console.print(table)


@suggest_app.command("dismiss")
def suggest_dismiss(
    rule_id: str = typer.Argument(..., help="Rule ID to dismiss"),
) -> None:
    """Dismiss a suggestion so it no longer appears."""
    from jarvis.suggestions import dismiss

    conn = get_db()
    dismiss(conn, rule_id)
    conn.close()
    console.print(f"[green]Dismissed:[/green] {rule_id}")


@suggest_app.command("snooze")
def suggest_snooze(
    rule_id: str = typer.Argument(..., help="Rule ID to snooze"),
    minutes: int = typer.Option(60, help="Snooze for this many minutes"),
) -> None:
    """Snooze a suggestion for a given number of minutes."""
    from jarvis.suggestions import snooze

    conn = get_db()
    snooze(conn, rule_id, minutes=minutes)
    conn.close()
    console.print(f"[green]Snoozed[/green] {rule_id} for {minutes} minutes.")


# --- GCal subcommands ---

gcal_app = typer.Typer(help="Manage Google Calendar accounts")
app.add_typer(gcal_app, name="gcal")


@gcal_app.command("auth")
def gcal_auth(
    name: str = typer.Argument(..., help="Account label, e.g. 'work' or 'personal'"),
    credentials: str = typer.Option(
        ..., "--credentials", "-c", help="Path to OAuth client credentials JSON"
    ),
) -> None:
    """Authenticate a Google account and save its token."""
    import shutil

    from jarvis.config import JARVIS_HOME
    from jarvis.integrations.gcal import authenticate

    src = Path(credentials).expanduser()
    if not src.exists():
        console.print(f"[red]File not found:[/red] {src}")
        raise typer.Exit(1)

    slug = name.lower().replace(" ", "_")
    dest = JARVIS_HOME / f"gcal_{slug}_creds.json"
    shutil.copy2(src, dest)
    console.print(f"Credentials copied to [bold]{dest}[/bold]")
    console.print("Opening browser for OAuth…")

    if not authenticate(name, str(dest)):
        console.print("[red]Authentication failed.[/red] Check the credentials file.")
        raise typer.Exit(1)

    console.print(f"[green]✓ Authenticated as[/green] [bold]{name}[/bold]")
    console.print("\nAdd this to [bold]~/.jarvis/config.toml[/bold]:\n")
    console.print(
        f"[[gcal.accounts]]\n"
        f'name = "{name}"\n'
        f'credentials_path = "{dest}"\n'
        f'calendar_ids = ["primary"]'
    )
    console.print(
        "\nThen run [bold]jarvis gcal list-calendars "
        + name
        + "[/bold] to see available calendars."
    )


@gcal_app.command("list-calendars")
def gcal_list_calendars(
    name: str = typer.Argument(..., help="Account label as set in config"),
) -> None:
    """List all calendars for a configured GCal account."""
    from jarvis.config import JarvisConfig
    from jarvis.integrations.gcal import list_calendars

    cfg = JarvisConfig.load()
    acct = next((a for a in cfg.gcal.accounts if a.name.lower() == name.lower()), None)
    if acct is None:
        console.print(f"[red]No account named '{name}' found in config.[/red]")
        raise typer.Exit(1)

    creds = str(Path(acct.credentials_path).expanduser())
    cals = list_calendars(name, creds)
    if not cals:
        console.print("[yellow]No calendars found or not authenticated.[/yellow]")
        return

    from rich.table import Table

    table = Table(title=f"Calendars for {name}")
    table.add_column("Name")
    table.add_column("ID")
    table.add_column("Primary")
    for c in cals:
        table.add_row(c["name"], c["id"], "✓" if c["primary"] else "")
    console.print(table)


@gcal_app.command("status")
def gcal_status() -> None:
    """Show configured GCal accounts and token status."""
    from jarvis.config import JarvisConfig
    from jarvis.integrations.gcal import _token_path

    cfg = JarvisConfig.load()
    if not cfg.gcal.accounts:
        console.print(
            "[yellow]No GCal accounts configured.[/yellow] "
            "Run [bold]jarvis gcal auth <name> --credentials <path>[/bold] to set one up."
        )
        return

    from rich.table import Table

    table = Table(title="GCal Accounts")
    table.add_column("Name")
    table.add_column("Token")
    table.add_column("Calendars")
    for acct in cfg.gcal.accounts:
        token = _token_path(acct.name)
        token_status = "[green]✓ saved[/green]" if token.exists() else "[red]missing[/red]"
        table.add_row(acct.name, token_status, ", ".join(acct.calendar_ids))
    console.print(table)


# --- PR Monitor subcommands ---

pr_app = typer.Typer(help="Monitor open pull requests")
app.add_typer(pr_app, name="pr")

_PR_MONITOR_PLIST_NAME = "com.jarvis.pr_monitor"
_PR_MONITOR_PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{_PR_MONITOR_PLIST_NAME}.plist"
)


@pr_app.command("monitor")
def pr_monitor_run(
    repo: list[str] = typer.Option([], help="Override repos (repeatable)"),
) -> None:
    """Run the PR monitor now and surface suggestions."""
    from jarvis.config import JarvisConfig
    from jarvis.pr_monitor import run_monitor

    cfg = JarvisConfig.load()
    conn = get_db()
    counts = run_monitor(
        conn,
        account_keys=cfg.pr_monitor.account_keys,
        repos=list(repo) or None,
        max_files=cfg.pr_monitor.max_files,
        max_lines=cfg.pr_monitor.max_lines,
        staging_patterns=cfg.pr_monitor.staging_patterns,
    )
    conn.close()

    console.print(
        f"Checked [bold]{counts['prs_checked']}[/bold] PRs — "
        f"CI failures: {counts['ci_failures']}, "
        f"review comments: {counts['review_comments']}, "
        f"ready to merge: {counts['ready_to_merge']}, "
        f"oversized: {counts['oversized']}, "
        f"staging deploys: {counts['staging_deploys']}"
    )


@pr_app.command("status")
def pr_status() -> None:
    """Show a table of open PRs across all configured accounts."""
    from jarvis.config import JarvisConfig
    from jarvis.pr_monitor import list_open_prs

    cfg = JarvisConfig.load()
    prs = list_open_prs(account_keys=cfg.pr_monitor.account_keys)

    if not prs:
        console.print("[yellow]No open PRs found.[/yellow]")
        return

    table = Table(title=f"Open PRs ({len(prs)})")
    table.add_column("Repo", no_wrap=True)
    table.add_column("#", justify="right", width=6)
    table.add_column("Title", no_wrap=False)
    table.add_column("Author", width=16)
    table.add_column("CI", width=8)
    table.add_column("Files", justify="right", width=6)

    ci_style = {"passing": "green", "failing": "red", "pending": "yellow", "unknown": "dim"}
    for pr in prs:
        draft_tag = " [dim](draft)[/dim]" if pr["draft"] else ""
        ci = pr["ci"]
        table.add_row(
            pr["repo"],
            str(pr["number"]),
            f"{pr['title'][:60]}{draft_tag}",
            pr["author"],
            f"[{ci_style.get(ci, 'dim')}]{ci}[/{ci_style.get(ci, 'dim')}]",
            str(pr["changed_files"]),
        )

    console.print(table)


@pr_app.command("fix")
def pr_fix(
    pr_number: int = typer.Argument(..., help="PR number to fix"),
    repo: str = typer.Option("", help="Repo (owner/name). Inferred from config if omitted."),
) -> None:
    """Show LLM-proposed fix for a failing CI check and optionally push a commit."""
    import keyring

    from jarvis.config import JarvisConfig
    from jarvis.pr_monitor import _check_ci_failure, _get

    cfg = JarvisConfig.load()
    token = None
    for key in cfg.pr_monitor.account_keys:
        t = keyring.get_password("jarvis", key)
        if t:
            token = t
            break

    if not token:
        console.print("[red]No GitHub token found in keychain.[/red]")
        raise typer.Exit(1)

    target_repo = repo or (cfg.github.repos[0] if cfg.github.repos else "")
    if not target_repo:
        console.print("[red]Specify --repo or configure [github] repos in config.[/red]")
        raise typer.Exit(1)

    from jarvis.db import API  # type: ignore[attr-defined]  # noqa: F401
    from jarvis.pr_monitor import API as GH_API

    pr = _get(f"{GH_API}/repos/{target_repo}/pulls/{pr_number}", token)
    if not pr:
        console.print(f"[red]PR #{pr_number} not found in {target_repo}.[/red]")
        raise typer.Exit(1)

    conn = get_db()
    suggestion = _check_ci_failure(conn, target_repo, pr, token)
    conn.close()

    if not suggestion:
        console.print(f"[green]No CI failure detected on PR #{pr_number}.[/green]")
        return

    console.print(f"\n[bold]CI Failure — PR #{pr_number}[/bold]\n")
    console.print(suggestion.message)
    console.print()

    push = typer.confirm("Push a fix commit to this branch?", default=False)
    if not push:
        return

    branch = pr.get("head", {}).get("ref", "")
    if not branch:
        console.print("[red]Could not determine branch name.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[yellow]Clone or switch to the branch '{branch}' and apply the fix manually,[/yellow]\n"
        "[yellow]then run `git push`. Auto-commit is not implemented yet.[/yellow]"
    )


# --- Schedule subcommands ---

schedule_app = typer.Typer(help="Manage automatic ingestion schedule")
app.add_typer(schedule_app, name="schedule")


_PLIST_NAME = "com.jarvis.ingest"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_NAME}.plist"


def _find_jarvis_bin() -> str:
    """Find the jarvis binary path."""
    import shutil

    path = shutil.which("jarvis")
    if path:
        return path
    # Fallback: use uv run
    uv = shutil.which("uv")
    if uv:
        return f"{uv} run jarvis"
    return "jarvis"


@schedule_app.command("install")
def schedule_install(
    interval: int = typer.Option(900, help="Interval in seconds (default: 900 = 15 min)"),
) -> None:
    """Install a launchd agent to run `jarvis ingest` automatically."""
    jarvis_bin = _find_jarvis_bin()

    # Build the program arguments
    if " " in jarvis_bin:
        # uv run jarvis case
        parts = jarvis_bin.split()
        program_args = parts + ["ingest", "--days", "1"]
    else:
        program_args = [jarvis_bin, "ingest", "--days", "1"]

    log_path = JARVIS_HOME / "ingest.log"
    local_bin = Path.home() / ".local" / "bin"
    path_val = f"/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:{local_bin}"
    args_xml = "".join(f"<string>{a}</string>" for a in program_args)

    plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>{args_xml}</array>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_val}</string>
    </dict>
</dict>
</plist>
"""
    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(plist_content)

    import subprocess

    subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(_PLIST_PATH)], capture_output=True, text=True)

    if result.returncode == 0:
        console.print(f"[green]Installed.[/green] Jarvis will ingest every {interval // 60} min.")
        console.print(f"  Plist: {_PLIST_PATH}")
        console.print(f"  Log: {JARVIS_HOME / 'ingest.log'}")
    else:
        console.print(f"[red]Failed to load:[/red] {result.stderr}")


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Remove the automatic ingestion schedule."""
    import subprocess

    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], capture_output=True)
        _PLIST_PATH.unlink()
        console.print("[green]Uninstalled.[/green] Automatic ingestion stopped.")
    else:
        console.print("[yellow]No schedule found.[/yellow]")


@schedule_app.command("status")
def schedule_status() -> None:
    """Check if automatic ingestion is running."""
    import subprocess

    result = subprocess.run(["launchctl", "list", _PLIST_NAME], capture_output=True, text=True)
    if result.returncode == 0:
        console.print(f"[green]Running.[/green] Plist: {_PLIST_PATH}")
        # Show last ingest log
        log_path = JARVIS_HOME / "ingest.log"
        if log_path.exists():
            lines = log_path.read_text().strip().splitlines()
            if lines:
                console.print("\nLast log lines:")
                for line in lines[-5:]:
                    console.print(f"  {line}")
    else:
        console.print("[yellow]Not running.[/yellow] Install with `jarvis schedule install`.")


@app.command()
def web(
    port: int = typer.Option(8745, help="Port to run on"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
) -> None:
    """Start the local web dashboard."""
    import uvicorn

    console.print(f"[bold]Jarvis Dashboard[/bold] at http://{host}:{port}")
    uvicorn.run("jarvis.web.app:app", host=host, port=port, reload=False)


@app.command()
def install() -> None:
    """Interactive first-run setup wizard."""
    from jarvis.installer import run_install

    run_install()


@app.command()
def menubar() -> None:
    """Start the macOS menu bar tray icon."""
    from jarvis.menubar import main

    main()


@app.command("pr-monitor")
def pr_monitor() -> None:
    """Check open PRs: explain CI failures, summarise reviews, auto-merge when green."""
    from jarvis.pr_monitor import run_pr_monitor

    run_pr_monitor()


@app.command()
def evolve(
    fresh: bool = typer.Option(False, "--fresh", help="Bypass cache."),
    create_pr: str = typer.Option(None, "--create-pr", help="Scaffold spec PR for feature."),
) -> None:
    """Re-rank feature backlog using your activity data."""
    from jarvis.evolve import run_evolve

    run_evolve(fresh=fresh, create_pr=create_pr)


@app.command()
def quit() -> None:
    """Stop the running Jarvis menu bar process."""
    from jarvis.launcher import quit_jarvis

    quit_jarvis()


@app.command()
def update() -> None:
    """Pull latest code and reinstall jarvis, then restart."""
    import subprocess

    from jarvis.launcher import _already_running, quit_jarvis

    # Find repo root: stored at ~/.jarvis/repo_path by `make install`
    repo_path_file = JARVIS_HOME / "repo_path"
    if repo_path_file.exists():
        repo = Path(repo_path_file.read_text().strip())
    else:
        # Fallback for editable installs (dev only)
        repo = Path(__file__).parent.parent
    if not (repo / "pyproject.toml").exists():
        console.print(
            "[red]Cannot find repo root.[/red] "
            "Run [bold]make install[/bold] from the jarvis repo to register its path."
        )
        raise typer.Exit(1)

    was_running = _already_running()
    if was_running:
        quit_jarvis()

    def _git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL
        ).strip()

    console.print("[blue]Checking for updates...[/blue]")
    try:
        before_sha = _git("rev-parse", "--short", "HEAD")
        subprocess.run(["git", "-C", str(repo), "fetch"], capture_output=True)
        remote_sha = _git("rev-parse", "--short", "origin/main")
    except Exception as e:
        console.print(f"[yellow]Could not check remote:[/yellow] {e}")
        before_sha = remote_sha = "unknown"

    if before_sha == remote_sha:
        console.print(f"[dim]Already at latest ({before_sha}).[/dim]")
    else:
        # Stash any local changes, switch to main, pull, then restore
        stashed = subprocess.run(
            ["git", "-C", str(repo), "stash", "--include-untracked"],
            capture_output=True,
            text=True,
        )
        had_stash = "No local changes" not in stashed.stdout
        subprocess.run(["git", "-C", str(repo), "checkout", "main"], capture_output=True, text=True)
        result = subprocess.run(
            ["git", "-C", str(repo), "pull", "origin", "main"], capture_output=True, text=True
        )
        if had_stash:
            subprocess.run(["git", "-C", str(repo), "stash", "pop"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[yellow]git pull failed:[/yellow] {result.stderr.strip()}")
        else:
            try:
                after_sha = _git("rev-parse", "--short", "HEAD")
            except Exception:
                after_sha = "unknown"
            console.print(f"[green]Pulled[/green] {before_sha} → {after_sha}")

    console.print("[blue]Reinstalling...[/blue]")
    # Build a wheel first so the installed copy is not live-linked to the repo
    build_result = subprocess.run(
        ["uv", "build", "--wheel", "-q"],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    if build_result.returncode != 0:
        console.print(f"[red]Build failed:[/red] {build_result.stderr.strip()}")
        raise typer.Exit(1)
    # Find the newest wheel
    wheels = sorted((repo / "dist").glob("jarvis-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        console.print("[red]No wheel found in dist/[/red]")
        raise typer.Exit(1)
    wheel = wheels[-1]
    result = subprocess.run(
        ["uv", "tool", "install", str(wheel), "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Install failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)

    # Read version from the freshly installed binary
    import shutil

    jarvis_bin = shutil.which("jarvis") or "jarvis"
    ver_result = subprocess.run([jarvis_bin, "--version"], capture_output=True, text=True)
    new_version = ver_result.stdout.strip()
    console.print(f"[green]✓ Updated.[/green] {new_version}")

    if was_running:
        from jarvis.launcher import launch

        launch()


# --- Setup subcommands ---

setup_app = typer.Typer(help="Configure Jarvis integrations")
app.add_typer(setup_app, name="setup")


@setup_app.command("profiles")
def setup_profiles_cmd() -> None:
    """Discover and label Firefox / Thunderbird profiles."""
    from jarvis.installer import setup_profiles

    setup_profiles()


if __name__ == "__main__":
    app()
