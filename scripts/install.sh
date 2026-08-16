#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/octopus-agent/octopus-agent.git"
MINIMAL=0
DEV=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[INFO]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
die()   { err "$@"; exit 1; }

# Audit S-09: never pipe a download straight into a shell. Download to a
# temp file, verify the pinned SHA-256, and only then execute. A mismatch
# (or a missing digest tool) fails closed — supply-chain protection for the
# three piped installers (pyenv.run / nvm install.sh / uv install.sh).
#   $1 = url, $2 = expected sha256, $3 = interpreter (bash|sh)
download_verify_run() {
    local url="$1" expected="$2" interpreter="$3"
    local tmp actual
    tmp="$(mktemp)" || die "cannot create temp file for download verification"
    if ! curl -fsSL "$url" -o "$tmp"; then
        rm -f "$tmp"
        die "download failed: $url"
    fi
    actual="$(shasum -a 256 "$tmp" 2>/dev/null | awk '{print $1}')"
    if [ -z "$actual" ]; then
        actual="$(sha256sum "$tmp" 2>/dev/null | awk '{print $1}')"
    fi
    if [ -z "$actual" ]; then
        rm -f "$tmp"
        die "no sha256 tool available to verify $url"
    fi
    if [ "$actual" != "$expected" ]; then
        rm -f "$tmp"
        die "checksum mismatch for $url (expected $expected, got $actual)"
    fi
    "$interpreter" "$tmp"
    local rc=$?
    rm -f "$tmp"
    return "$rc"
}

for arg in "$@"; do
    case "$arg" in
        --minimal) MINIMAL=1 ;;
        --dev)     DEV=1 ;;
        --help|-h)
            echo "Usage: $0 [--minimal] [--dev]"
            echo ""
            echo "  --minimal   Skip Node.js / frontend installation"
            echo "  --dev       Include development dependencies (pytest, ruff, etc.)"
            exit 0
            ;;
        *) die "Unknown argument: $arg (run --help for usage)" ;;
    esac
done

detect_os() {
    local uname_out
    uname_out="$(uname -s)"
    case "${uname_out}" in
        Linux*)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                echo "wsl2"
            else
                echo "linux"
            fi
            ;;
        Darwin*) echo "macos" ;;
        *) die "Unsupported OS: ${uname_out}" ;;
    esac
}

OS="$(detect_os)"
info "Detected OS: ${OS}"

require_cmd() {
    command -v "$1" &>/dev/null
}

python_version_ok() {
    local py="$1"
    if ! require_cmd "$py"; then
        return 1
    fi
    local ver
    ver="$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
    local major minor
    IFS='.' read -r major minor <<< "$ver"
    [[ "$major" -gt 3 ]] && return 0
    [[ "$major" -eq 3 && "$minor" -ge 11 ]] && return 0
    return 1
}

find_python() {
    for candidate in python3.12 python3.11 python3 python; do
        if python_version_ok "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_python_pyenv() {
    info "Installing Python 3.12 via pyenv..."
    if ! require_cmd pyenv; then
        info "Installing pyenv..."
        download_verify_run https://pyenv.run 1065197a9fff657e0e2941e4ca8c8b6e72833833466b777b9eddd0fff335ec41 bash 2>/dev/null || {
            warn "pyenv install failed, trying brew..."
            if require_cmd brew; then
                brew install pyenv
            else
                die "Cannot install pyenv. Please install Python 3.11+ manually."
            fi
        }
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
        if ! require_cmd pyenv; then
            die "pyenv not found after installation. Restart your shell and re-run this script."
        fi
    fi
    pyenv install -s 3.12
    pyenv rehash
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
}

install_python_system() {
    info "Attempting system package manager Python install (no sudo)..."
    case "$OS" in
        linux|wsl2)
            if require_cmd apt-get; then
                apt-get update -qq 2>/dev/null && \
                apt-get install -y -qq python3.12 python3.12-venv 2>/dev/null || \
                apt-get install -y -qq python3.11 python3.11-venv 2>/dev/null || \
                { warn "System Python install failed (no sudo), falling back to pyenv..."; install_python_pyenv; }
            elif require_cmd dnf; then
                dnf install -y python3.12 python3.12-pip 2>/dev/null || \
                dnf install -y python3.11 python3.11-pip 2>/dev/null || \
                install_python_pyenv
            else
                install_python_pyenv
            fi
            ;;
        macos)
            if require_cmd brew; then
                brew install python@3.12 2>/dev/null || brew install python@3.11
            else
                install_python_pyenv
            fi
            ;;
    esac
}

PYTHON=""
if PYTHON="$(find_python)"; then
    ok "Python found: $PYTHON ($("$PYTHON" --version 2>&1))"
else
    warn "Python 3.11+ not found"
    install_python_pyenv
    PYTHON="$(find_python)" || {
        install_python_system
        PYTHON="$(find_python)" || die "Python 3.11+ still not found after installation attempts"
    }
    ok "Python installed: $PYTHON ($("$PYTHON" --version 2>&1))"
fi

if [[ "$MINIMAL" -eq 0 ]]; then
    node_version_ok() {
        if ! require_cmd node; then
            return 1
        fi
        local ver
        ver="$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)"
        [[ "$ver" -ge 20 ]]
    }

    if node_version_ok; then
        ok "Node.js found: $(node -v)"
    else
        warn "Node.js 20+ not found"
        info "Installing nvm..."
        export NVM_DIR="$HOME/.nvm"
        if [[ ! -d "$NVM_DIR" ]]; then
            download_verify_run https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh abdb525ee9f5b48b34d8ed9fc67c6013fb0f659712e401ecd88ab989b3af8f53 bash
        fi
        [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
        nvm install --lts
        nvm use --lts
        if node_version_ok; then
            ok "Node.js installed: $(node -v)"
        else
            die "Node.js 20+ still not found after nvm install"
        fi
    fi
fi

if require_cmd uv; then
    ok "uv found: $(uv --version 2>&1)"
else
    warn "uv not found"
    info "Installing uv..."
    download_verify_run https://astral.sh/uv/install.sh 504511fbbbd811aeaba6738abc79408956b6c7da0ca35437b3dcc24a41efc111 sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if require_cmd uv; then
        ok "uv installed: $(uv --version 2>&1)"
    else
        die "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree &>/dev/null; then
    ok "Git repository detected at ${PROJECT_DIR}"
else
    info "Not inside a git repo, cloning ${REPO_URL}..."
    CLONE_DIR="$HOME/octopus-agent"
    if [[ -d "$CLONE_DIR" && -d "$CLONE_DIR/.git" ]]; then
        ok "Repo already cloned at ${CLONE_DIR}, pulling latest..."
        git -C "$CLONE_DIR" pull --ff-only || warn "git pull failed, continuing with existing checkout"
    else
        git clone "$REPO_URL" "$CLONE_DIR"
        ok "Repo cloned to ${CLONE_DIR}"
    fi
    PROJECT_DIR="$CLONE_DIR"
fi

cd "$PROJECT_DIR"

if [[ -d ".venv" ]]; then
    ok "Virtual environment already exists at .venv"
else
    info "Creating virtual environment with uv..."
    uv venv .venv --python 3.11
    ok "Virtual environment created"
fi

source .venv/bin/activate

info "Installing Python dependencies..."
if [[ "$DEV" -eq 1 ]]; then
    uv pip install -e ".[all,dev]"
else
    uv pip install -e ".[all]"
fi
ok "Python dependencies installed"

if [[ "$MINIMAL" -eq 0 ]]; then
    if [[ -d "frontend" ]]; then
        info "Installing frontend dependencies..."
        (cd frontend && corepack enable 2>/dev/null; pnpm install --frozen-lockfile)
        ok "Frontend dependencies installed"
    else
        warn "frontend/ directory not found, skipping frontend setup"
    fi
fi

info "Running health check..."
if python -c "from runtime.adapters.channels import *; print('OK')" 2>/dev/null; then
    ok "Health check passed"
else
    warn "Health check: channel adapters import had warnings (non-fatal)"
    python -c "from runtime.platform.doctor import Doctor; report = Doctor().run(); print(report.summary())" 2>/dev/null || \
        warn "Doctor check could not run — install may still be OK"
fi

echo ""
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${GREEN}  ✓ Octopus Agent installed successfully!${NC}\n"
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
echo ""
echo "  Project:  ${PROJECT_DIR}"
echo "  Python:   $PYTHON ($("$PYTHON" --version 2>&1))"
if [[ "$MINIMAL" -eq 0 ]]; then
    echo "  Node.js:  $(node -v 2>/dev/null || echo 'N/A')"
fi
echo "  venv:     ${PROJECT_DIR}/.venv"
echo ""
echo "  Next steps:"
echo "    1. Activate the environment:"
echo "       source ${PROJECT_DIR}/.venv/bin/activate"
echo ""
echo "    2. Copy and edit config:"
echo "       cp config.example.yaml config.yaml"
echo ""
echo "    3. Set your API key:"
echo "       export ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "    4. Run the doctor:"
echo "       python -c \"from runtime.platform.doctor import Doctor; print(Doctor().run().summary())\""
echo ""
echo "    5. Start the server:"
echo "       python -m runtime serve"
if [[ "$MINIMAL" -eq 0 ]]; then
    echo ""
    echo "    6. Start the frontend (in another terminal):"
    echo "       cd ${PROJECT_DIR}/frontend && pnpm dev"
fi
echo ""
