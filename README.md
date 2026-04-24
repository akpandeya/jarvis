# Jarvis

Personal engineering assistant — tracks work, summarises activity, monitors PRs, and proactively surfaces suggestions via a macOS menu bar icon.

## Install (from repo)

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Node.js 20+](https://nodejs.org/) (for building the React dashboard).

```bash
git clone git@github.com:akpandeya/jarvis.git
cd jarvis
make install      # builds frontend, installs `jarvis` and `jarvis-menubar` to ~/.local/bin
jarvis install    # interactive setup: GitHub token, repos, autostart agents
```

`make install` builds the React frontend into `jarvis/web/static/` and then uses `uv tool install` — no venv activation needed afterwards. `jarvis` is available in any new terminal immediately.

## First-run setup

`jarvis install` will prompt for:
- GitHub personal access token (stored in macOS Keychain)
- Repos to monitor (`owner/repo`)
- Whether to install launchd boot agents (ingest every 15 min, PR monitor every 2 h, menu bar persistent)

Requires the [Claude Code CLI](https://claude.ai/code) for AI features (`jarvis standup`, `jarvis context`, etc.).

## Usage

```bash
jarvis ingest          # pull latest activity from all sources
jarvis standup         # AI standup summary
jarvis suggest         # show proactive suggestions
jarvis pr status       # open PR table with CI status
jarvis web             # open local dashboard at http://localhost:8745
jarvis menubar         # start menu bar tray icon
```

## Development

Backend:

```bash
make dev     # create .venv and install dev dependencies
make test    # run pytest
make lint    # ruff check
make format  # ruff format
```

Frontend (React + Vite, lives in `frontend/`):

```bash
make web-install   # one-time: install node_modules
make web-build     # build production bundle into jarvis/web/static/
make web-dev       # run Vite dev server on :5173 (proxies /api → :8745)
```

For full-stack dev, run `jarvis web` (backend on :8745) in one terminal and `make web-dev` in another. Navigate to <http://localhost:5173>.
