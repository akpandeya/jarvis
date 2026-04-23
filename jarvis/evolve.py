"""jarvis evolve — re-ranks the feature backlog using activity signals and the LLM.

Spec: docs/specs/evolve.md
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rich.console import Console

from jarvis.db import get_db

console = Console()

# Path to TODO.md relative to the repo root (two levels up from this file)
_TODO_PATH = Path(__file__).parent.parent / "docs" / "TODO.md"
_SPECS_DIR = Path(__file__).parent.parent / "docs" / "specs"

_KV_KEY = "evolve_last_run"
_CACHE_TTL_HOURS = 24

_SYSTEM_PROMPT = (
    "You are an engineering assistant that re-ranks a feature backlog. "
    "You will receive the current TODO.md content and usage signals. "
    "Return ONLY a JSON array (no markdown fences, no extra text) where each element has: "
    '{"feature": "<name>", "phase": "<phase>", "rationale": "<one sentence>", '
    '"score": <number 0-100>}. '
    "Rank by score descending. Use the usage signals to favour features that address "
    "the tools and workflows the user actually uses most."
)


def _collect_signals(conn) -> dict:  # type: ignore[type-arg]
    """Collect activity signals from the database (F2)."""
    from jarvis.db import command_frequency, source_distribution, top_urls

    cmd_freq = command_frequency(conn, limit=5)
    url_tops = top_urls(conn, limit=5)
    src_dist = source_distribution(conn, days=30)
    return {
        "top_commands": cmd_freq,
        "top_url_domains": url_tops,
        "source_distribution": src_dist,
    }


def _has_activity(conn) -> bool:  # type: ignore[type-arg]
    """Return True if there is any activity in the DB (F8)."""
    event_row = conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
    activity_row = conn.execute("SELECT COUNT(*) as cnt FROM activity_log").fetchone()
    return (event_row["cnt"] or 0) > 0 or (activity_row["cnt"] or 0) > 0


def _call_llm(todo_content: str, signals: dict) -> str:  # type: ignore[type-arg]
    """Call the LLM via the claude CLI (F4)."""
    import shutil

    if not shutil.which("claude"):
        raise RuntimeError("claude CLI not found. Install Claude Code first.")

    signals_text = (
        f"Top 5 CLI commands: {signals['top_commands']}\n"
        f"Top 5 URL domains: {signals['top_url_domains']}\n"
        f"Event source distribution (last 30d): {signals['source_distribution']}\n"
    )

    user_message = (
        f"## Current TODO.md\n\n{todo_content}\n\n"
        f"## Activity Signals\n\n{signals_text}\n\n"
        "Re-rank the features listed in TODO.md. Return only the JSON array."
    )

    result = subprocess.run(
        ["claude", "-p", "--bare", "--append-system-prompt", _SYSTEM_PROMPT],
        input=user_message,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")

    return result.stdout.strip()


def _parse_llm_response(raw: str) -> list[dict]:  # type: ignore[type-arg]
    """Parse JSON array from LLM response. Returns empty list on failure."""
    # Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        return []


def _get_cached(conn) -> list[dict] | None:  # type: ignore[type-arg]
    """Return cached result if it exists and is within TTL (F5)."""
    from jarvis.db import kv_get

    raw = kv_get(conn, _KV_KEY)
    if not raw:
        return None
    try:
        cached = json.loads(raw)
        saved_at_str = cached.get("saved_at")
        if not saved_at_str:
            return None
        saved_at = datetime.fromisoformat(saved_at_str)
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=UTC)
        age = datetime.now(UTC) - saved_at
        if age < timedelta(hours=_CACHE_TTL_HOURS):
            return cached.get("items")
        return None
    except Exception:
        return None


def _save_cache(conn, items: list[dict]) -> None:  # type: ignore[type-arg]
    """Save items to the kv cache with current timestamp (F5)."""
    from jarvis.db import kv_set

    payload = {"saved_at": datetime.now(UTC).isoformat(), "items": items}
    kv_set(conn, _KV_KEY, json.dumps(payload))


def _print_ranked(items: list[dict]) -> None:  # type: ignore[type-arg]
    """Print the ranked list (F3)."""
    console.print("\n[bold]Feature Backlog — Re-ranked by Activity Signals[/bold]\n")
    for i, item in enumerate(items, 1):
        feature = item.get("feature", "(unknown)")
        phase = item.get("phase", "?")
        rationale = item.get("rationale", "")
        score = item.get("score", "")
        score_str = f"  [dim](score: {score})[/dim]" if score != "" else ""
        console.print(f"[bold]{i}.[/bold] {feature} [dim][{phase}][/dim]{score_str}")
        if rationale:
            console.print(f"   [italic]{rationale}[/italic]")
    console.print()


def _slugify(name: str) -> str:
    """Convert a feature name to a file-system-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _create_pr(feature_name: str) -> None:
    """Scaffold a stub spec and open a GitHub PR (F7)."""
    slug = _slugify(feature_name)
    spec_path = _SPECS_DIR / f"{slug}.md"

    if spec_path.exists():
        console.print(f"[yellow]Spec already exists:[/yellow] {spec_path}")
    else:
        stub = (
            f"---\n"
            f"name: {slug}\n"
            f"description: TODO — fill in description\n"
            f"component: jarvis/{slug}.py\n"
            f"---\n\n"
            f"# Spec — {feature_name}\n\n"
            f"**Component:** `jarvis/{slug}.py`\n\n"
            f"TODO — describe the component here.\n\n"
            f"## Behaviours\n\n"
            f"### F1. TODO\n\n"
            f"**WHEN** TODO **THEN** the component **SHALL** TODO.\n"
        )
        spec_path.write_text(stub)
        console.print(f"[green]Wrote spec:[/green] {spec_path}")

    # Determine repo root
    repo_root = Path(__file__).parent.parent

    # Create a new branch and commit the spec
    branch = f"spec/{slug}"
    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "checkout", "-b", branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]git checkout failed:[/red] {e.stderr.strip()}")
        return

    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "add", str(spec_path)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "commit",
                "-m",
                f"spec: stub spec for {feature_name}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]git commit failed:[/red] {e.stderr.strip()}")
        return

    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "push", "-u", "origin", branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]git push failed:[/red] {e.stderr.strip()}")
        return

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"spec: {feature_name}",
                "--body",
                f"Stub spec for **{feature_name}**.\n\nGenerated by `jarvis evolve --create-pr`.",
                "--base",
                "main",
                "--head",
                branch,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if result.returncode == 0:
            console.print(f"[green]PR created:[/green] {result.stdout.strip()}")
        else:
            console.print(f"[red]gh pr create failed:[/red] {result.stderr.strip()}")
    except FileNotFoundError:
        console.print("[red]gh CLI not found. Install GitHub CLI to open PRs.[/red]")


def run_evolve(fresh: bool = False, create_pr: str | None = None) -> None:
    """Main entry point for `jarvis evolve`."""
    if create_pr:
        _create_pr(create_pr)
        return

    conn = get_db()

    try:
        # F8: no activity data
        if not _has_activity(conn):
            console.print(
                "[yellow]No activity data found.[/yellow] "
                "Run [bold]jarvis ingest[/bold] to pull in your recent work, "
                "then run [bold]jarvis evolve[/bold] again."
            )
            return

        # F5/F6: cache check
        if not fresh:
            cached = _get_cached(conn)
            if cached is not None:
                console.print("[dim]Using cached result (run --fresh to bypass).[/dim]")
                _print_ranked(cached)
                return

        # Read TODO.md
        if not _TODO_PATH.exists():
            console.print(f"[red]TODO.md not found at {_TODO_PATH}[/red]")
            return
        todo_content = _TODO_PATH.read_text()

        # Collect signals (F2)
        signals = _collect_signals(conn)

        # Call LLM (F1, F4)
        console.print("[bold]Analysing backlog with activity signals...[/bold]")
        try:
            raw = _call_llm(todo_content, signals)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            return

        items = _parse_llm_response(raw)
        if not items:
            console.print("[yellow]Could not parse LLM response as JSON. Raw output:[/yellow]")
            console.print(raw)
            return

        # Sort by score descending
        items.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Cache result (F5)
        _save_cache(conn, items)

        # Print ranked list (F3)
        _print_ranked(items)

    finally:
        conn.close()
