# CLAUDE.md -- AutoSwarm Office

## Critical Paths

- `apps/nexus-api/src/main.py` -- FastAPI application entry point
- `apps/office-ui/src/app/page.tsx` -- Office UI root page
- `packages/orchestrator/src/orchestrator.py` -- Swarm orchestration engine
- `packages/permissions/src/matrix.py` -- HITL permission matrix
- `packages/permissions/src/engine.py` -- Permission evaluation engine
- `packages/inference/src/router.py` -- LLM model routing logic

## Port Assignments

| Port | Service | Notes |
|------|---------|-------|
| 4300 | nexus-api | Central API |
| 4301 | office-ui | Next.js frontend |
| 4302 | admin | Admin dashboard |
| 4303 | colyseus | Game state server |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Commands

```bash
make dev          # Start all services (TS + Python)
make test         # Run all tests
make lint         # Run all linters
make typecheck    # TypeScript + mypy
make build        # Build all packages
make docker-dev   # Start Postgres + Redis
make db-migrate   # Run Alembic migrations
make db-seed      # Seed departments and agents

pnpm dev          # TypeScript services only
pnpm build        # Build TypeScript packages
pnpm lint         # ESLint
pnpm test         # TypeScript tests
pnpm typecheck    # TypeScript type checking

uv run pytest     # Python tests
uv run ruff check .  # Python linting
uv run mypy .     # Python type checking
```

## MADFAM Ecosystem

- **Janua** handles all authentication. Never implement custom auth. Use the
  `get_current_user` dependency in FastAPI and the Next.js middleware for session
  validation. Janua tokens are JWTs with `sub`, `email`, `roles`, and `org_id` claims.

- **Dhanam** handles billing and subscriptions. Compute token budgets are enforced
  by the orchestrator package and tracked in the `compute_token_ledger` table.
  Use the billing router at `apps/nexus-api/src/routers/billing.py`.

- **Enclii** handles deployment. The `.enclii.yml` defines all three services.
  The `deploy-enclii.yml` GitHub Actions workflow builds images and notifies Enclii.

- Read sibling repo `llms-full.txt` files for full API surfaces of Janua, Dhanam,
  and Enclii.

## Coding Standards

### Python
- **Linter**: ruff (target py312, line-length 100)
- **Type checker**: mypy (strict mode)
- **Models**: pydantic for all request/response schemas
- **ORM**: SQLAlchemy with async sessions
- **Tests**: pytest with pytest-asyncio
- **Imports**: isort via ruff, `autoswarm` as known-first-party

### TypeScript
- **Strict mode**: enabled in all tsconfig.json files
- **Linter**: ESLint with shared config from `packages/config/eslint`
- **Formatter**: Prettier
- **Build**: Turborepo for monorepo orchestration
- **Package manager**: pnpm with workspace protocol

## Git Workflow

- Feature branches only -- never commit directly to `main`.
- Conventional commits enforced by commitlint:
  `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`
- PRs require CI to pass before merge.

## Architecture Notes

- The Redis queue key is `autoswarm:tasks` (LPUSH to enqueue, BRPOP to dequeue).
- WebSocket approval events use the `ConnectionManager` singleton in
  `apps/nexus-api/src/ws.py`.
- LangGraph `interrupt()` is used to pause agent execution for HITL approval.
- Synergy bonuses stack multiplicatively (see `packages/orchestrator/src/synergy.py`).
- The permission matrix is evaluated by `packages/permissions/src/engine.py` before
  every tool invocation in the worker.
