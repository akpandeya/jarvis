.PHONY: install dev test lint format clean

# Install jarvis CLI system-wide using uv tool install.
# After this, `jarvis` is available in any terminal without activating a venv.
install:
	uv build --wheel -q
	uv tool install $$(ls -t dist/jarvis-*.whl | head -1) --force
	mkdir -p ~/.jarvis && echo "$$(pwd)" > ~/.jarvis/repo_path

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
	rm -rf dist/ .venv/
