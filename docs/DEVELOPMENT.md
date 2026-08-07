# Development Guide

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | >= 20 | https://nodejs.org or `nvm install 20` |
| pnpm | >= 9 | `npm install -g pnpm` |
| Python | >= 3.12 | https://www.python.org or `pyenv install 3.12` |
| UV | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | latest | https://www.docker.com |

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/YOUR-ORG/selva-office.git
cd selva-office

# 2. Run first-time setup (checks prereqs, installs deps, creates .env)
bash scripts/setup.sh

# 3. Start PostgreSQL and Redis
make docker-dev

# 4. Start all services in development mode (API + UI + Colyseus + Worker)
make dev
```

After startup, these URLs are available:

| Service | URL |
|---------|-----|
| Office UI (landing) | http://localhost:4301 |
| Office UI (demo) | http://localhost:4301/demo |
| Office UI (office) | http://localhost:4301/office |
| Nexus API | http://localhost:4300 |
| API docs (Swagger) | http://localhost:4300/api/v1/docs (disabled when `ENVIRONMENT=production`) |
| Colyseus | ws://localhost:4303 |
| Gateway | http://localhost:4304/health (heartbeat daemon) |

## Running Services Individually

Each service can be started on its own for focused development.

### Nexus API (Python)

```bash
uv run --directory apps/nexus-api fastapi dev src/main.py --port 4300
```

### Office UI (Next.js)

```bash
cd apps/office-ui
pnpm dev
```

### Colyseus (Node.js)

```bash
cd apps/colyseus
pnpm dev
```

### Worker (Python — LangGraph task consumer)

```bash
make worker
```

### Gateway (Node.js)

```bash
cd apps/gateway
pnpm dev
```

## Environment Variables

All environment variables are documented in `.env.example` at the project root.
Running `scripts/setup.sh` will copy this file to `.env` if one does not already
exist. The main categories are:

- **Infrastructure** -- `DATABASE_URL`, `REDIS_URL`
- **Auth (Janua)** -- `JANUA_ISSUER_URL`, `JANUA_CLIENT_ID`, `JANUA_CLIENT_SECRET`
- **Billing (Dhanam)** -- `DHANAM_API_URL`, `DHANAM_WEBHOOK_SECRET`
- **AI Inference** -- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`
- **OpenClaw** -- `OPENCLAW_API_KEY`, `OPENCLAW_MEMORY_DIR`
- **Colyseus** -- `COLYSEUS_SECRET`
- **Ports** -- `NEXUS_API_PORT`, `OFFICE_UI_PORT`, `ADMIN_PORT`, `COLYSEUS_PORT`

## Testing

```bash
# Run all tests (TypeScript + Python)
make test

# TypeScript tests only (via Turborepo, 137 tests across 8 suites)
pnpm test

# Python tests only (via pytest, 165 tests)
uv run pytest

# Python tests with coverage
uv run pytest --cov

# TypeScript tests with coverage
pnpm test -- --coverage

# Run a specific Python test file
uv run pytest tests/test_permissions.py -v
```

### TypeScript Test Suites

| Package | Suite | Tests |
|---------|-------|-------|
| `@selva/shared-types` | Type guards and validators | 22 |
| `@selva/colyseus` | Movement handlers | 25 |
| `@selva/colyseus` | Interaction handlers | 15 |
| `@selva/gateway` | Memory management | 20 |
| `@selva/ui` | Button component | 14 |
| `@selva/ui` | AgentCard component | 12 |
| `@selva/ui` | ApprovalModal component | 12 |
| `@selva/office-ui` | useApprovals hook | 17 |

## Linting and Formatting

```bash
# Run all linters
make lint

# TypeScript linting (ESLint via Turborepo)
pnpm lint

# Python linting (Ruff)
uv run ruff check .

# Python type checking (mypy, strict mode)
uv run mypy .

# Format all files
make format

# TypeScript formatting (Prettier)
pnpm format

# Python formatting (Ruff)
uv run ruff format .
```

## Database Operations

```bash
# Start dev databases (PostgreSQL + Redis)
make docker-dev

# Run Alembic migrations
make db-migrate

# Seed default departments and agents
make db-seed

# Stop dev databases
make docker-down
```

## Docker

```bash
# Start infrastructure only (Postgres + Redis)
make docker-dev

# Start full stack with all services
make docker-up

# Stop everything
make docker-down
```

## Sprite Assets

The Office UI uses pixel-art sprite PNGs for the Phaser game layer. These are
committed to the repo at `apps/office-ui/public/assets/` so they're available
without extra build steps.

To regenerate the sprites (e.g. after changing colors or adding new roles):

```bash
# Generates 12 PNG files (7 sprites, 1 tileset, 4 UI icons)
make generate-assets
```

The generator (`scripts/generate-assets.js`) uses `@napi-rs/canvas` to
programmatically draw pixel-art characters, tilesets, and icons. The Phaser
`BootScene` loads these files and falls back to canvas-generated colored
rectangles if any PNG is missing.

## Build

```bash
# Build all TypeScript packages
pnpm build

# Build Python packages
uv build

# Build everything
make build
```

## Git Workflow

This project uses conventional commits, checked by commitlint from a husky
`commit-msg` hook. `pnpm install` installs the hook (via the `prepare` script),
so it runs on every local `git commit` after a fresh clone and install.

```bash
# Create a feature branch
git checkout -b feat/my-feature

# Commit with conventional format
git commit -m "feat(nexus-api): add agent level-up endpoint"

# Push and open a PR
git push -u origin feat/my-feature
```

Commit types: `build`, `chore`, `ci`, `deploy`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `rollback`, `style`, `test`. (`deploy` and `rollback` are
written by the release workflows, not by hand.)

Scopes are free-form -- use whatever names the area you touched. The header must
be 100 characters or less.

To bypass the hook in an emergency: `HUSKY=0 git commit ...`.
