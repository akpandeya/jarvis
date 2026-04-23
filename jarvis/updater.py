"""Version check against GitHub Releases."""

from __future__ import annotations


def get_latest_version() -> str | None:
    """Return latest release version string from GitHub, or None on error."""
    try:
        import httpx

        r = httpx.get(
            "https://api.github.com/repos/akpandeya/jarvis/releases/latest",
            timeout=5,
        )
        tag = r.json().get("tag_name", "")
        return tag.lstrip("v") or None
    except Exception:
        return None


def update_available() -> bool:
    """Return True if a newer release exists than the installed version."""
    from jarvis import __version__

    latest = get_latest_version()
    if not latest:
        return False
    try:
        return tuple(int(x) for x in latest.split(".")) > tuple(
            int(x) for x in __version__.split(".")
        )
    except ValueError:
        return False
