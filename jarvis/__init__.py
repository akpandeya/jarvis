"""Jarvis — Personal engineering assistant."""

import subprocess as _subprocess
from pathlib import Path as _Path

__version__ = "0.2.5"

# In a dev checkout (.git present), append the git SHA so it's distinguishable
# from a clean installed copy (where .git is absent from the uv tool cache).
_git_dir = _Path(__file__).parent.parent / ".git"
if _git_dir.exists():
    try:
        _sha = _subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_Path(__file__).parent.parent),
            stderr=_subprocess.DEVNULL,
            text=True,
        ).strip()
        __version__ = f"{__version__}-dev+{_sha}"
    except Exception:
        pass
