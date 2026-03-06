#!/usr/bin/env bash
set -euo pipefail

# ── AutoSwarm Office - First-Time Setup ──────────────────────────────
# This script checks prerequisites, installs dependencies, and prepares
# the local development environment.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[OK]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[!!]${NC}  $1"; }
fail()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo ""
echo "=== AutoSwarm Office Setup ==="
echo ""

# ── Check prerequisites ──────────────────────────────────────────────

echo "Checking prerequisites..."
echo ""

# Node.js >= 20
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 20 ]; then
        info "Node.js $NODE_VERSION"
    else
        fail "Node.js >= 20 required (found $NODE_VERSION). Install via https://nodejs.org or nvm."
    fi
else
    fail "Node.js is not installed. Install v20+ from https://nodejs.org or use nvm."
fi

# pnpm
if command -v pnpm &> /dev/null; then
    PNPM_VERSION=$(pnpm --version)
    info "pnpm $PNPM_VERSION"
else
    fail "pnpm is not installed. Install via: npm install -g pnpm"
fi

# Python >= 3.12
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
        info "Python $PY_VERSION"
    else
        fail "Python >= 3.12 required (found $PY_VERSION). Install from https://www.python.org or pyenv."
    fi
else
    fail "Python 3 is not installed. Install v3.12+ from https://www.python.org or use pyenv."
fi

# uv
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version | awk '{print $2}')
    info "uv $UV_VERSION"
else
    fail "uv is not installed. Install via: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# Docker
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
    info "Docker $DOCKER_VERSION"
else
    warn "Docker is not installed. You will need it for local databases. Install from https://www.docker.com"
fi

echo ""

# ── Environment file ─────────────────────────────────────────────────

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        info "Created .env from .env.example"
    else
        warn ".env.example not found -- skipping .env creation"
    fi
else
    info ".env already exists -- skipping"
fi

echo ""

# ── Install dependencies ─────────────────────────────────────────────

echo "Installing Node.js dependencies..."
pnpm install
info "Node.js dependencies installed"

echo ""
echo "Installing Python dependencies..."
uv sync
info "Python dependencies installed"

echo ""

# ── Done ──────────────────────────────────────────────────────────────

echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Start infrastructure:  make docker-dev"
echo "  2. Run all services:      make dev"
echo "  3. Open the office UI:    http://localhost:4301"
echo ""
echo "Useful commands:"
echo "  make test     Run all tests (TS + Python)"
echo "  make lint     Run all linters"
echo "  make db-seed  Seed default departments and agents"
echo ""
