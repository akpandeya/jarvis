"""Interactive first-run setup wizard and launchd agent management."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _find_jarvis_bin() -> str:
    import shutil

    path = shutil.which("jarvis")
    if path:
        return path
    uv = shutil.which("uv")
    if uv:
        return f"{uv} run jarvis"
    return "jarvis"


def _write_plist(
    label: str,
    args_xml: str,
    extra_keys: str,
    log_path: Path,
    run_at_load: bool = True,
) -> None:
    from jarvis.config import JARVIS_HOME

    local_bin = Path.home() / ".local" / "bin"
    path_val = f"/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:{local_bin}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    run_at_load_val = "<true/>" if run_at_load else "<false/>"
    plist_path.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>{args_xml}</array>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>RunAtLoad</key>
    {run_at_load_val}
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_val}</string>
        <key>JARVIS_HOME</key>
        <string>{JARVIS_HOME}</string>
    </dict>
{extra_keys}</dict>
</plist>
""")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)


def _args_xml(parts: list[str]) -> str:
    return "".join(f"<string>{p}</string>" for p in parts)


def install_launchd_agents(jarvis_bin: str | None = None) -> None:
    """Install (or reinstall) all three launchd agents."""
    from jarvis.config import JARVIS_HOME

    bin_ = jarvis_bin or _find_jarvis_bin()
    parts = bin_.split() if " " in bin_ else [bin_]

    _write_plist(
        "com.jarvis.ingest",
        _args_xml(parts + ["ingest", "--days", "1"]),
        "    <key>StartInterval</key>\n    <integer>900</integer>\n",
        JARVIS_HOME / "ingest.log",
    )
    _write_plist(
        "com.jarvis.pr_monitor",
        _args_xml(parts + ["pr-monitor"]),
        "    <key>StartInterval</key>\n    <integer>7200</integer>\n",
        JARVIS_HOME / "pr_monitor.log",
        run_at_load=False,
    )
    _write_plist(
        "com.jarvis.menubar",
        _args_xml(parts + ["menubar"]),
        "    <key>KeepAlive</key>\n    <true/>\n",
        JARVIS_HOME / "menubar.log",
    )


def run_install() -> None:
    """Interactive setup wizard."""
    import shutil

    import keyring
    import typer
    from rich.console import Console
    from rich.panel import Panel

    from jarvis.config import CONFIG_PATH, ensure_jarvis_home
    from jarvis.db import init_db

    console = Console()
    console.print(Panel("[bold]Jarvis Setup[/bold]", expand=False))

    # 1. Create ~/.jarvis/
    ensure_jarvis_home()
    init_db()
    console.print("[green]✓[/green] ~/.jarvis/ initialised")

    # 2. GitHub token
    existing = keyring.get_password("jarvis", "github_token")
    if existing:
        update = typer.confirm("GitHub token already stored. Replace it?", default=False)
        if update:
            token = typer.prompt("GitHub personal access token", hide_input=True)
            keyring.set_password("jarvis", "github_token", token)
            console.print("[green]✓[/green] Token updated")
    else:
        token = typer.prompt("GitHub personal access token (scope: repo)", hide_input=True)
        keyring.set_password("jarvis", "github_token", token)
        console.print("[green]✓[/green] Token stored in Keychain")

    # 3. Repos
    console.print("\nEnter GitHub repos to monitor (owner/repo). Empty line to finish.")
    repos: list[str] = []
    while True:
        repo = typer.prompt("  Repo", default="")
        if not repo:
            break
        if "/" in repo:
            repos.append(repo)
        else:
            console.print("[yellow]  Format must be owner/repo[/yellow]")

    if repos:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                data = tomllib.load(f)
        else:
            data = {}

        data.setdefault("github", {})["repos"] = repos
        _write_toml(CONFIG_PATH, data)
        console.print(f"[green]✓[/green] {len(repos)} repo(s) saved to config")

    # 4. Claude CLI check
    if shutil.which("claude"):
        console.print("[green]✓[/green] claude CLI found")
    else:
        console.print(
            "[yellow]⚠[/yellow] claude CLI not found. "
            "Install it from https://claude.ai/code to enable AI features."
        )

    # 5. Profile discovery
    console.print()
    setup_profiles(console=console, interactive=True)

    # 6. Autostart
    console.print()
    if typer.confirm("Start Jarvis automatically at login (menu bar + background agents)?"):
        install_launchd_agents()
        console.print("[green]✓[/green] Launchd agents installed (ingest, pr_monitor, menubar)")
    else:
        console.print(
            "[dim]Skipped. Run `jarvis schedule install` later to enable background agents.[/dim]"
        )

    # 6. Done
    console.print(
        Panel(
            "[bold green]Jarvis is ready![/bold green]\n\n"
            "  [cyan]jarvis web[/cyan]       — open dashboard\n"
            "  [cyan]jarvis menubar[/cyan]   — start menu bar icon\n"
            "  [cyan]jarvis suggest[/cyan]   — show suggestions\n"
            "  [cyan]jarvis ingest[/cyan]    — pull latest activity",
            title="Done",
            expand=False,
        )
    )


def setup_profiles(console=None, interactive: bool = True) -> None:
    """Discover Firefox and Thunderbird profiles and prompt user to label them."""
    from rich.console import Console
    from rich.table import Table

    from jarvis.activity import discover_firefox_profiles, discover_thunderbird_profiles
    from jarvis.config import CONFIG_PATH

    con = console or Console()

    ff_profiles = [p for p in discover_firefox_profiles() if p["has_history"]]
    tb_profiles = [p for p in discover_thunderbird_profiles() if p["has_db"]]

    if not ff_profiles and not tb_profiles:
        con.print("[dim]No Firefox or Thunderbird profiles found.[/dim]")
        return

    # Show discovered profiles
    if ff_profiles:
        t = Table(title="Firefox profiles found", show_header=True)
        t.add_column("#", width=3)
        t.add_column("Path stem")
        t.add_column("Detected name")
        for i, p in enumerate(ff_profiles, 1):
            t.add_row(str(i), p["path"], p["name"])
        con.print(t)

    if tb_profiles:
        t = Table(title="Thunderbird profiles found", show_header=True)
        t.add_column("#", width=3)
        t.add_column("Path stem")
        for i, p in enumerate(tb_profiles, 1):
            t.add_row(str(i), p["path"])
        con.print(t)

    if not interactive:
        return

    # Read existing config
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    data: dict = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

    # Label Firefox profiles
    if ff_profiles:
        con.print("\nLabel Firefox profiles (Enter to keep detected name, skip to exclude):")
        labeled: list[dict] = []
        for p in ff_profiles:
            import typer

            label = typer.prompt(f"  '{p['name']}' label", default=p["name"])
            if label.lower() != "skip":
                labeled.append({"path": p["path"], "label": label})
        if labeled:
            data.setdefault("firefox", {})["profiles"] = labeled
            con.print(f"[green]✓[/green] {len(labeled)} Firefox profile(s) saved")

    # Work domains for Thunderbird
    if tb_profiles:
        con.print("\nThunderbird work email domains (comma-separated, e.g. mycompany.com):")
        import typer

        domains_input = typer.prompt("  Work domains", default="")
        domains = [d.strip() for d in domains_input.split(",") if d.strip()]
        if domains:
            data.setdefault("thunderbird", {})["work_domains"] = domains
            con.print(f"[green]✓[/green] Work domains saved: {', '.join(domains)}")

    if data:
        _write_toml(CONFIG_PATH, data)


def _write_toml(path: Path, data: dict) -> None:
    """Write a minimal TOML file from a dict (no dependency on tomli-w)."""
    lines: list[str] = []
    for section, value in data.items():
        if isinstance(value, dict):
            lines.append(f"\n[{section}]")
            for k, v in value.items():
                if isinstance(v, list):
                    items = ", ".join(f'"{x}"' for x in v)
                    lines.append(f"{k} = [{items}]")
                elif isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                else:
                    lines.append(f"{k} = {v}")
    path.write_text("\n".join(lines) + "\n")
