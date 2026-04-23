#!/usr/bin/env bash
# Jarvis bootstrap — installs Python 3.11+ via pyenv if needed, downloads the
# latest jarvis.pyz from GitHub Releases, and runs `jarvis install`.
set -euo pipefail

REPO="akpandeya/jarvis"
INSTALL_DIR="${HOME}/.local/bin"
PYZ_PATH="${INSTALL_DIR}/jarvis.pyz"
LINK_PATH="${INSTALL_DIR}/jarvis"
MIN_PYTHON_MINOR=11

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()    { echo "  [jarvis] $*"; }
success() { echo "  [jarvis] ✓ $*"; }
warn()    { echo "  [jarvis] ⚠ $*" >&2; }
die()     { echo "  [jarvis] ✗ $*" >&2; exit 1; }

_python_ok() {
    local bin="${1:-python3}"
    if ! command -v "$bin" &>/dev/null; then return 1; fi
    local minor
    minor=$("$bin" -c "import sys; print(sys.version_info.minor)")
    local major
    major=$("$bin" -c "import sys; print(sys.version_info.major)")
    [[ "$major" -eq 3 && "$minor" -ge $MIN_PYTHON_MINOR ]]
}

# ---------------------------------------------------------------------------
# Step 1: ensure Python 3.11+
# ---------------------------------------------------------------------------

if _python_ok python3; then
    success "Python 3 $(python3 --version 2>&1 | awk '{print $2}') found"
    PYTHON=python3
else
    warn "Python 3.${MIN_PYTHON_MINOR}+ not found — installing via pyenv"

    if ! command -v pyenv &>/dev/null; then
        info "Installing pyenv..."
        curl -sSf https://pyenv.run | bash

        # Add pyenv init to the appropriate shell profile
        for rc in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
            if [[ -f "$rc" ]]; then
                if ! grep -q 'pyenv init' "$rc"; then
                    {
                        echo ''
                        echo '# pyenv'
                        echo 'export PYENV_ROOT="$HOME/.pyenv"'
                        echo 'export PATH="$PYENV_ROOT/bin:$PATH"'
                        echo 'eval "$(pyenv init -)"'
                    } >> "$rc"
                fi
            fi
        done

        export PYENV_ROOT="${HOME}/.pyenv"
        export PATH="${PYENV_ROOT}/bin:${PATH}"
        eval "$(pyenv init -)"
    fi

    PYTHON_VERSION="3.11.9"
    info "Installing Python ${PYTHON_VERSION} (this may take a few minutes)..."
    pyenv install "${PYTHON_VERSION}" --skip-existing
    pyenv global "${PYTHON_VERSION}"
    PYTHON="$(pyenv which python3)"
    success "Python ${PYTHON_VERSION} installed"
fi

# ---------------------------------------------------------------------------
# Step 2: download latest jarvis.pyz
# ---------------------------------------------------------------------------

info "Fetching latest release..."
DOWNLOAD_URL=$(curl -sSf "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep browser_download_url \
    | grep '\.pyz' \
    | cut -d'"' -f4)

if [[ -z "$DOWNLOAD_URL" ]]; then
    die "No .pyz artifact found in latest release. Check https://github.com/${REPO}/releases"
fi

mkdir -p "${INSTALL_DIR}"
info "Downloading ${DOWNLOAD_URL}..."
curl -sSfL "${DOWNLOAD_URL}" -o "${PYZ_PATH}"
chmod +x "${PYZ_PATH}"

# Create a wrapper script so the correct Python is used
cat > "${LINK_PATH}" <<WRAPPER
#!/usr/bin/env bash
exec "${PYTHON}" "${PYZ_PATH}" "\$@"
WRAPPER
chmod +x "${LINK_PATH}"

success "jarvis installed at ${LINK_PATH}"

# Ensure ~/.local/bin is on PATH in this shell session
export PATH="${INSTALL_DIR}:${PATH}"

# ---------------------------------------------------------------------------
# Step 3: run the interactive installer
# ---------------------------------------------------------------------------

info "Running setup wizard..."
"${LINK_PATH}" install
