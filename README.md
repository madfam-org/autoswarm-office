# Selva Office

Gamified multi-agent business orchestration platform. Manage your digital enterprise
as an Auto Chess-style RPG -- draft AI agents, assign them to departments, and approve
their actions from a 2D virtual office using a gamepad.

## Architecture

Selva Office is a polyglot monorepo with TypeScript frontends and Python backends.

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

### Python Packages (`packages/`)

- `selva-redis-pool`: Standardized Redis dependency for async pub/sub and distributed locking.
- `selva-permissions`: Strict Janua RBAC dependency injecting FastAPI role assertions globally,
  and the platform/tenant audience boundary for tools and skills.
- `selva-orchestrator`: Swarm orchestration engine (synergy rules, Thompson Sampling bandit,
  puppeteer mode) integrated with the Enclii platform lifecycle.
- `selva-workflows`: YAML-defined LangGraph workflows for autonomous multi-agent execution.
- `selva-skills`: Procedural skills registry (core + community tiers) with the
  AgentSkills SKILL.md format and locale variants.
- `selva-tools`: 240+ built-in tools across file ops, code exec, git, web, data, comms,
  artifacts, MCP, and Mexican-market integrations (Karafiel, Dhanam, PhyneCRM, Tezca).
- `selva-permissions`: HITL permission engine with skill-based overrides and audience guard.
- `selva-memory`: Per-agent FAISS vector store and Experience/Reflexion learning loop.
- `selva-calendar`: Google + Microsoft calendar adapters.
- `selva-observability`: Shared structured logging, request-id correlation, Sentry, OTel.
- `selva-a2a`: Agent-to-Agent protocol package (AgentCard discovery, task exchange, SSE).
- `selva-plugins`: Plugin loader for third-party agent extensions.
- `selva-sdk`: Python async/sync client + `selva` CLI for dispatching tasks programmatically.
- `madfam-inference`: LLM provider routing (OpenAI, Anthropic, Ollama, DeepInfra,
  Together, Fireworks, SiliconFlow, Moonshot) with task-type assignment and vision support.
- `madfam-revenue-loop-probe`: Shared revenue-loop instrumentation primitives.

## Monorepo Structure

```
selva-office/
  apps/
    nexus-api/         FastAPI -- central orchestration API
    office-ui/         Next.js + Phaser -- spatial office UI
    admin/             Next.js -- admin dashboard
    colyseus/          Colyseus -- game state server
    gateway/           OpenClaw -- heartbeat daemon
    workers/           LangGraph -- task execution
  packages/
    shared-types/      Shared TypeScript types
    ui/                Shared React components (incl. Pixelact namespace)
    config/            ESLint, TypeScript, and logging presets
    orchestrator/      Swarm orchestration (Python)
    permissions/       HITL permission engine + audience boundary (Python)
    inference/         LLM provider routing (Python, `madfam_inference`)
    skills/            Procedural skills registry (Python, `selva_skills`)
    tools/             Built-in tool library (Python, `selva_tools`)
    workflows/         YAML→LangGraph compiler (Python, `selva_workflows`)
    memory/            Per-agent FAISS + Experience/Reflexion (Python)
    calendar/          Google + Microsoft adapters (Python)
    a2a/               Agent-to-Agent protocol (Python)
    sdk/               Python SDK + `selva` CLI
    redis-pool/        Shared Redis singleton with circuit breaker (Python)
    observability/     Logging, OTel, Sentry helpers (Python)
    plugins/           Plugin loader (Python)
    revenue-loop-probe/  Revenue-loop instrumentation (Python)
  infra/
    docker/            Dockerfiles and Compose
    k8s/               Kubernetes manifests (production base + staging overlay)
    argocd/            ArgoCD Application manifests
    cloudflare/        DNS + redirect rules
  scripts/             Setup, seed, asset generation, and map generation scripts
  docs/                Architecture and development guides
```

## Port Assignments

> See [docs/PORTS.md](docs/PORTS.md) for canonical port assignments.

| Port | Service |
|------|---------|
| 4300 | Nexus API |
| 4301 | Office UI |
| 4302 | Admin Dashboard |
| 4303 | Colyseus |
| 4304 | Gateway (heartbeat daemon health + metrics HTTP) |
| 4305 | Workers (health + metrics HTTP) |
| 5432 | PostgreSQL |
| 6379 | Redis |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Human-in-the-Loop Flow](docs/HITL_FLOW.md)
- [MADFAM Integration Guide](docs/INTEGRATION.md)
- [Autonomous Cleanroom Protocol (ACP)](docs/AUTONOMOUS_CLEANROOM_PROTOCOL.md)
- [Ecosystem Context (self-contained)](ECOSYSTEM.md)

## MADFAM Ecosystem

Selva Office is part of the MADFAM platform and integrates with:

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
