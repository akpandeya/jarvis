#!/usr/bin/env bash
# Build a self-contained jarvis.pyz using shiv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VERSION=$(python3 -c "import jarvis; print(jarvis.__version__)" 2>/dev/null \
    || python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

OUTPUT="dist/jarvis-${VERSION}.pyz"
mkdir -p dist

echo "Building ${OUTPUT}..."

# Install shiv into the current environment if not present
python3 -m pip install --quiet shiv

# Build: bundle all deps + source, entry point = jarvis.cli:app
shiv \
    --compressed \
    --python "/usr/bin/env python3" \
    --entry-point "jarvis.cli:app" \
    --output-file "${OUTPUT}" \
    .

echo "✓ Built ${OUTPUT}"
echo "  Test with: python3 ${OUTPUT} --help"
