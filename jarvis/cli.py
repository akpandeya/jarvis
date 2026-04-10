from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from jarvis.config import DB_PATH, ensure_jarvis_home, JarvisConfig, CONFIG_PATH
from jarvis.db import event_count, get_db, init_db, query_events, search_events

app = typer.Typer(help="Jarvis — Personal engineering assistant")
console = Console()


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
    console.print('  [bold]python -c "import keyring; keyring.set_password(\'jarvis\', \'github_token\', \'ghp_YOUR_TOKEN\')"[/bold]')


@app.command()
def ingest(
    days: int = typer.Option(7, help="How many days back to fetch"),
    source: Optional[str] = typer.Option(None, help="Only ingest from this source"),
) -> None:
    """Pull latest events from all configured integrations."""
    ensure_jarvis_home()
    from jarvis.ingest import ingest_all

    console.print(f"[bold]Ingesting events (last {days} days)...[/bold]")
    total = ingest_all(days=days, source_filter=source)
    conn = get_db()
    console.print(f"\n[green]Done.[/green] {total} events ingested. Total in DB: {event_count(conn)}")
    conn.close()


@app.command()
def log(
    source: Optional[str] = typer.Option(None, help="Filter by source (git_local, github)"),
    project: Optional[str] = typer.Option(None, help="Filter by project name"),
    days: int = typer.Option(7, help="How many days back to show"),
    limit: int = typer.Option(30, help="Max events to show"),
) -> None:
    """Show recent activity events."""
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
    project: Optional[str] = typer.Option(None, help="Scope to a specific project"),
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
    project: Optional[str] = typer.Option(None, help="Scope to a specific project"),
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
    from jarvis.brain import answer_query
    from rich.markdown import Markdown

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
    project: Optional[str] = typer.Option(None, help="Scope to a specific project"),
    days: int = typer.Option(2, help="How many days of context to include"),
    raw: bool = typer.Option(False, "--raw", help="Output raw markdown (for piping/hooks)"),
) -> None:
    """Show a context briefing — what you've been working on recently."""
    from jarvis.memory import generate_context
    from rich.markdown import Markdown

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
    project: Optional[str] = typer.Option(None, help="Project name"),
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
    project: Optional[str] = typer.Option(None, help="Filter by project"),
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
    project: Optional[str] = typer.Option(None, help="Associate with a project"),
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
    from jarvis.brain import _call_claude, _format_events
    from rich.markdown import Markdown

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
        console.print(f"  jira: enabled (via jira-cli) — {len(keys)} project(s)" if keys else "  jira: enabled (via jira-cli, default project)")
    else:
        console.print("  jira: [yellow]disabled[/yellow]")

    if config.gcal.calendar_id:
        console.print(f"  gcal: calendar '{config.gcal.calendar_id}'")
    else:
        console.print("  gcal: [yellow]not configured[/yellow]")


if __name__ == "__main__":
    app()
