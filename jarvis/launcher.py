"""Non-blocking daemon launcher with PID-file idempotency.

Starts the menu bar icon and web server as detached background processes.
start_new_session=True ensures they survive terminal close (SIGHUP is not
delivered to a new process group).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from subprocess import DEVNULL

from rich.console import Console

_PID_FILE = Path.home() / ".jarvis" / "jarvis.pid"
_WEB_PID_FILE = Path.home() / ".jarvis" / "jarvis-web.pid"
_DASHBOARD_URL = "http://localhost:8745"
console = Console()


def _find_jarvis() -> str:
    import shutil

    return shutil.which("jarvis") or sys.executable + " -m jarvis"


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _already_running() -> bool:
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        if _is_pid_alive(pid):
            return True
        _PID_FILE.unlink(missing_ok=True)
        return False
    except ValueError:
        _PID_FILE.unlink(missing_ok=True)
        return False


def _start_daemon(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        stdout=DEVNULL,
        stderr=DEVNULL,
        stdin=DEVNULL,
        start_new_session=True,  # detach from terminal — survives terminal close
    )


def _write_pid(pid: int) -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _write_web_pid(pid: int) -> None:
    _WEB_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WEB_PID_FILE.write_text(str(pid))


def clear_pid() -> None:
    """Called by menubar quit_app to clean up the PID file."""
    _PID_FILE.unlink(missing_ok=True)
    _WEB_PID_FILE.unlink(missing_ok=True)


def _kill_pid_file(pid_file: Path, label: str) -> bool:
    """Send SIGTERM to the PID in pid_file. Returns True if killed."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 15)  # SIGTERM
        pid_file.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError):
        pid_file.unlink(missing_ok=True)
        return False
    except PermissionError:
        console.print(f"[red]Permission denied stopping {label}.[/red]")
        return False


def quit_jarvis() -> None:
    """Terminate the running Jarvis menubar and web server processes."""
    menubar_stopped = _kill_pid_file(_PID_FILE, "menubar")
    web_stopped = _kill_pid_file(_WEB_PID_FILE, "web server")
    # Fallback: kill whatever is on the web port (handles stale processes)
    _kill_port(_WEB_PORT)

    if menubar_stopped or web_stopped:
        console.print("[green]Jarvis stopped.[/green]")
    else:
        console.print("[dim]Jarvis is not running.[/dim]")


_WEB_PORT = 8745


def _kill_port(port: int) -> None:
    """Kill any process already bound to port (cleans up stale web servers)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        for pid_str in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid_str), 15)
            except (ValueError, ProcessLookupError, PermissionError):
                pass
    except FileNotFoundError:
        pass


def launch() -> None:
    """Start menubar + web server as background daemons if not already running."""
    if _already_running():
        console.print("[dim]Jarvis is already running.[/dim]")
        return

    # Kill any stale web server that survived a previous unclean quit
    _kill_port(_WEB_PORT)

    jarvis = _find_jarvis()
    menubar_proc = _start_daemon([jarvis, "menubar"])
    web_proc = _start_daemon([jarvis, "web"])
    _write_pid(menubar_proc.pid)
    _write_web_pid(web_proc.pid)

    console.print(
        f"[green]Jarvis started.[/green] Menu bar icon active — dashboard at {_DASHBOARD_URL}"
    )
