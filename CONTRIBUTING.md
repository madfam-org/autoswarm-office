# Contributing to Selva Office

Thank you for your interest in contributing to Selva Office! This guide covers everything you need to get started.

## Prerequisites

- **Node.js** >= 22.12 (see `.nvmrc`; `nvm use` picks it up)
- **pnpm** >= 9
- **Python** >= 3.12
- **uv** (Python package manager)
- **Docker** >= 24
- **PostgreSQL** >= 16 (or use Docker Compose)

macOS:

```bash
brew install node pnpm python uv docker
```

## Project Structure

```
selva-office/
  apps/
    nexus-api/       # Agent orchestration API (Python/FastAPI)
    office-ui/       # Management console (Next.js)
    colyseus/        # Real-time collaboration (Node.js/Colyseus)
    gateway/         # Message gateway (Python)
    admin/           # Admin console (Next.js)
    workers/         # Agent workers (Python/LangGraph)
```

## Local Development Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR-ORG/selva-office
cd selva-office

# 2. Install Node.js dependencies
pnpm install

# 3. Install Python dependencies
uv sync --directory apps/nexus-api
uv sync --directory apps/gateway
uv sync --directory apps/workers

# 4. Start infrastructure
docker compose up -d postgres redis

# 5. Run database migrations
make db-migrate

# 6. Start all services
make dev
```

## Development Workflow

### Branch Strategy

We use **trunk-based development** on `main`.

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes with small, focused commits
3. Open a PR when ready for review

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(nexus-api): add agent memory persistence
fix(workers): handle LLM timeout gracefully
docs(readme): update architecture diagram
chore(deps): bump langchain to 0.3
```

### Validation Before Commit

```bash
# Run all checks
make lint
make test

# Or run individually:
# Python
uv run --directory apps/nexus-api ruff check .
uv run --directory apps/workers ruff check .

# TypeScript
pnpm --filter @selva/office-ui lint
pnpm --filter @selva/admin lint
```

### Testing

```bash
# All tests
make test

# Python tests
uv run --directory apps/nexus-api pytest
uv run --directory apps/workers pytest

# Node.js tests
pnpm --filter @selva/office-ui test
pnpm --filter @selva/colyseus test
```

## Pull Request Process

1. Ensure all checks pass (`make lint && make test`)
2. Write a clear PR description explaining **what** and **why**
3. Keep PRs focused -- one feature or fix per PR
4. Request review from a maintainer
5. Address review feedback with new commits (don't force-push)

## Schema codegen (Python ⇄ TypeScript wire types)

`packages/shared-types/src/generated/api.ts` mirrors the nexus-api
OpenAPI schema. It is auto-generated from the FastAPI app's Pydantic
models and route signatures and committed to the repo so PR diffs
show the type impact of every API change.

When you add or change anything that affects the wire shape -- a
Pydantic model, a route signature, a query parameter, a response
type -- regenerate the file:

```bash
pnpm generate-types
```

Commit the result alongside your Python changes. CI runs the same
command and `git diff --exit-code`s the generated dir; forgetting
to regenerate fails the `schema-drift` job and blocks the PR.

The hand-written domain types in `packages/shared-types/src/*.ts`
(camelCase) and the generated wire types under `generated/api.ts`
(snake_case) coexist on purpose -- see
[packages/shared-types/README.md](packages/shared-types/README.md)
for the conversion convention.

## Code Style

- **Python**: Follow PEP 8. We use `ruff` for linting and formatting
- **TypeScript**: Follow the existing patterns. We use ESLint + Prettier
- **Agent Prompts**: Keep prompts in dedicated files, not inline strings

## Security

- **Never** commit API keys or LLM provider credentials
- Use environment variables for all secrets
- See [SECURITY.md](./SECURITY.md) for vulnerability reporting

## License

By contributing to Selva Office, you agree that your contributions will be licensed under the [AGPL-3.0 License](./LICENSE).
