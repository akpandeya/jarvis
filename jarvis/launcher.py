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
_DASHBOARD_URL = "http://localhost:8745"
console = Console()


def _find_jarvis() -> str:
    import shutil

    return shutil.which("jarvis") or sys.executable + " -m jarvis"


def _already_running() -> bool:
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence only
        return True
    except (ValueError, ProcessLookupError, PermissionError):
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


def clear_pid() -> None:
    """Called by menubar quit_app to clean up the PID file."""
    _PID_FILE.unlink(missing_ok=True)


def launch() -> None:
    """Start menubar + web server as background daemons if not already running."""
    if _already_running():
        console.print("[dim]Jarvis is already running.[/dim]")
        return

    jarvis = _find_jarvis()
    menubar_proc = _start_daemon([jarvis, "menubar"])
    _start_daemon([jarvis, "web"])
    _write_pid(menubar_proc.pid)

    console.print(
        f"[green]Jarvis started.[/green] Menu bar icon active — dashboard at {_DASHBOARD_URL}"
    )
