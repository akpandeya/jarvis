"""macOS menu bar tray app."""

from __future__ import annotations

import subprocess
import webbrowser

_DASHBOARD_URL = "http://localhost:8745"
_SERVER_PROCESS: subprocess.Popen | None = None


def _find_jarvis() -> str:
    import shutil

    return shutil.which("jarvis") or "jarvis"


def main() -> None:
    try:
        import rumps
    except ImportError:
        print("rumps is required for the menu bar app: pip install rumps")
        raise SystemExit(1)

    jarvis_bin = _find_jarvis()

    class JarvisApp(rumps.App):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("J", quit_button=None)
            self.menu = [
                rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
                rumps.MenuItem("Run Ingest", callback=self.run_ingest),
                rumps.MenuItem("↻ Run PR Monitor", callback=self.run_pr_monitor),
                rumps.MenuItem("⬆ Update Jarvis", callback=self.update_jarvis),
                rumps.MenuItem("Suggestions", callback=self.show_suggestions),
                None,
                rumps.MenuItem("Quit Jarvis", callback=self.quit_app),
            ]
            self._update_item: rumps.MenuItem | None = None
            self._last_update_check: str = ""

        @rumps.timer(60)
        def refresh(self, _: object) -> None:
            self._refresh_badge()
            self._check_update()

        def _refresh_badge(self) -> None:
            try:
                from jarvis.db import get_db
                from jarvis.suggestions import get_pending

                conn = get_db()
                pending = get_pending(conn)
                conn.close()
                n = len(pending)
                self.title = "J ●" if n else "J"
            except Exception:
                pass

        def _check_update(self) -> None:
            import datetime

            today = datetime.date.today().isoformat()
            if today == self._last_update_check:
                return
            self._last_update_check = today
            try:
                from jarvis.updater import get_latest_version, update_available

                if update_available():
                    latest = get_latest_version()
                    label = f"Update available: v{latest}"
                    if self._update_item is None:
                        self._update_item = rumps.MenuItem(label)
                        self.menu.insert_after("Suggestions", self._update_item)
                    else:
                        self._update_item.title = label
            except Exception:
                pass

        def open_dashboard(self, _: object) -> None:
            global _SERVER_PROCESS
            if _SERVER_PROCESS is None or _SERVER_PROCESS.poll() is not None:
                _SERVER_PROCESS = subprocess.Popen(
                    [jarvis_bin, "web"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                import time

                time.sleep(1.5)
            webbrowser.open(_DASHBOARD_URL)

        def run_ingest(self, _: object) -> None:
            subprocess.Popen(
                [jarvis_bin, "ingest", "--days", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        def run_pr_monitor(self, _: object) -> None:
            subprocess.Popen(
                [jarvis_bin, "pr-monitor"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            rumps.notification("Jarvis", "PR Monitor", "Running PR check in background…")

        def update_jarvis(self, _: object) -> None:
            subprocess.Popen(
                [jarvis_bin, "update"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            rumps.notification("Jarvis", "Update", "Updating Jarvis in background…")

        def show_suggestions(self, _: object) -> None:
            try:
                result = subprocess.run(
                    [jarvis_bin, "suggest"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                text = result.stdout.strip() or "No suggestions right now."
                # Strip ANSI escape codes for the alert dialog
                import re

                text = re.sub(r"\x1b\[[0-9;]*m", "", text)
                rumps.alert(title="Jarvis Suggestions", message=text[:500])
            except Exception as exc:
                rumps.alert(title="Error", message=str(exc))

        def quit_app(self, _: object) -> None:
            global _SERVER_PROCESS
            if _SERVER_PROCESS and _SERVER_PROCESS.poll() is None:
                _SERVER_PROCESS.terminate()
            from jarvis.launcher import clear_pid

            clear_pid()
            rumps.quit_application()

    JarvisApp().run()
