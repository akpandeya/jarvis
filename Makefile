.PHONY: install dev test lint format clean web-build web-dev web-install

# Install jarvis CLI system-wide using uv tool install.
# Builds the React frontend first so the wheel ships with the static bundle.
install: web-build
	uv build --wheel -q
	uv tool install $$(ls -t dist/jarvis-*.whl | head -1) --force
	mkdir -p ~/.jarvis && echo "$$(pwd)" > ~/.jarvis/repo_path

# Build the React frontend into jarvis/web/static/ so FastAPI can serve it.
web-build:
	cd frontend && npm ci --no-audit --no-fund
	cd frontend && npm run build

# Run frontend Vite dev server + backend together.
# Use two terminals: one for `jarvis web`, one for this target.
# Vite proxies /api → http://127.0.0.1:8745.
web-dev:
	cd frontend && npm run dev

# Install frontend deps only (first-time setup).
web-install:
	cd frontend && npm install --no-audit --no-fund

# Set up a dev virtualenv (for running tests / IDE support).
dev:
	uv sync --group dev

test:
	uv run pytest -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

clean:
	rm -rf dist/ .venv/ jarvis/web/static/ frontend/node_modules/
