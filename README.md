# AutoSwarm Office

Gamified multi-agent business orchestration platform. Manage your digital enterprise
as an Auto Chess-style RPG -- draft AI agents, assign them to departments, and approve
their actions from a 2D virtual office using a gamepad.

## Architecture

AutoSwarm Office is a polyglot monorepo with TypeScript frontends and Python backends.

```
Office UI (Next.js + Phaser) <---> Colyseus (real-time state sync)
         |
    Nexus API (FastAPI) <---> Workers (LangGraph)
         |                         |
    PostgreSQL              Redis (task queue)
                                   |
                              Gateway (OpenClaw heartbeats)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full component diagram and
data flow documentation.

## Quick Start

```bash
# 1. Run first-time setup
bash scripts/setup.sh

# 2. Start PostgreSQL and Redis
make docker-dev

# 3. Start all services
make dev
```

## Monorepo Structure

```
autoswarm-office/
  apps/
    nexus-api/         FastAPI -- central orchestration API
    office-ui/         Next.js + Phaser -- spatial office UI
    colyseus/          Colyseus -- game state server
    gateway/           OpenClaw -- heartbeat daemon
    workers/           LangGraph -- task execution
  packages/
    shared-types/      Shared TypeScript types
    ui/                Shared React components
    config/            ESLint and TypeScript presets
    orchestrator/      Swarm orchestration (Python)
    permissions/       HITL permission engine (Python)
    inference/         LLM provider routing (Python)
  infra/
    docker/            Dockerfiles and Compose
    k8s/               Kubernetes manifests
  scripts/             Setup and seed scripts
  docs/                Architecture and development guides
```

## Port Assignments

| Port | Service |
|------|---------|
| 4300 | Nexus API |
| 4301 | Office UI |
| 4302 | Admin Dashboard |
| 4303 | Colyseus |
| 5432 | PostgreSQL |
| 6379 | Redis |

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Human-in-the-Loop Flow](docs/HITL_FLOW.md)
- [MADFAM Integration Guide](docs/INTEGRATION.md)

## MADFAM Ecosystem

AutoSwarm Office is part of the MADFAM platform and integrates with:

- **Janua** -- OpenID Connect authentication (ports 4100-4104)
- **Dhanam** -- Billing, subscriptions, and compute token budgets
- **Enclii** -- Deployment orchestration via ArgoCD (ports 4200-4204)

## Contributing

1. Create a feature branch from `main`.
2. Use conventional commits: `feat(scope): description`, `fix(scope): description`.
3. Open a pull request -- CI must pass before merge.
4. Commits are enforced by commitlint via husky pre-commit hooks.

## License

AGPL-3.0
