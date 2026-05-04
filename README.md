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

## Outbound Reddit Posting (operator runbook)

Tenant swarms can submit text posts to a single subreddit via the
`reddit_post` tool (`packages/tools/src/selva_tools/builtins/reddit_tools.py`).
The tool is gated by:

1. **Mandatory creds** — env vars `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`,
   `REDDIT_USER_AGENT`, `REDDIT_REFRESH_TOKEN`. Missing any one raises
   `ToolNotConfiguredError` (no placeholder ever shipped).
2. **Per-subreddit policy ConfigMap** — mounted at
   `/etc/selva/subreddit_policies.yaml` (sample at
   `infra/k8s/configmaps/subreddit-policies-default.yaml`). Default for
   any unlisted subreddit: `disclosure_required: true`.
3. **Mandatory AI disclosure footer** — appended automatically when the
   per-subreddit policy requires it. Idempotent — agents that
   pre-stamp the footer are not double-stamped.
4. **30-min Redis rate-limit per subreddit** — `selva:reddit:last_post:{subreddit}`
   key with 30-min TTL.
5. **HITL gate via the `reddit_promo_v1` built-in playbook** —
   `require_approval=True`, `financial_cap_cents=0`, `token_budget=20_000`.

### Operator provisioning steps

1. Create a Reddit "script-type" OAuth app at
   <https://www.reddit.com/prefs/apps>.
2. Use the script-app installed-flow to mint a refresh token (see PRAW
   docs).
3. Store the four secrets in Vault, sync to the `autoswarm` namespace
   K8s Secret used by the worker Deployment.
4. `kubectl apply -f infra/k8s/configmaps/subreddit-policies-default.yaml`
   to ship the policy ConfigMap.
5. Mount the ConfigMap on workers + nexus-api. Bump the worker
   Deployment annotation to force re-roll on policy changes.
6. Publish a real disclosure page at <https://madfam.io/ai-disclosure>
   before going live (the footer URL is a placeholder until then).

`X` (Twitter), LinkedIn, and crossposting are explicitly out of scope
for this MVP.

## Outbound Bluesky / AT Protocol Posting (operator runbook)

Tenant swarms can submit text posts to Bluesky via the `bluesky_post`
tool (`packages/tools/src/selva_tools/builtins/bluesky_tools.py`). The
tool mirrors the Reddit MVP shape and is gated by:

1. **Mandatory per-persona credentials** — env vars
   `BLUESKY_HANDLE_<PERSONA_ID>` (e.g. `madfam.bsky.social`) and
   `BLUESKY_APP_PASSWORD_<PERSONA_ID>` (16-char app password,
   NOT the account login password). Missing either raises
   `ToolNotConfiguredError` (no placeholder ever shipped).
2. **300-character hard limit, including the disclosure footer** —
   Bluesky's per-post limit is 300 chars. The mandatory disclosure
   footer is ~36 chars, leaving ~264 chars for promo content. If user
   text alone overflows 300, or text + footer overflows, the tool
   raises `PostTooLongError` (no silent truncation — agent must
   rewrite tighter). Document any longer drafts as a thread-of-replies
   (out of scope for v1; v2 ships threading helpers).
3. **Mandatory AI disclosure footer** — every post gets the suffix
   `\n\n— Posted by an AI agent on behalf of MADFAM` appended
   automatically. Idempotent — agents that pre-stamp the footer are
   not double-stamped.
4. **30-min Redis rate-limit per persona** —
   `selva:bluesky:last_post:{persona_id}` key with 30-min TTL.
   Bluesky's underlying API limit is high (5000 points/hr); the
   conservative cadence here is for promo content, not API hygiene.
5. **`langs` field** — default `["en"]`. Pass `langs=["es"]` for
   Karafiel/Dhanam Spanish promo copy so Bluesky's discovery feeds
   surface the post to the right audience.
6. **HITL gate via the `bluesky_promo_v1` built-in playbook** —
   `require_approval=True`, `financial_cap_cents=0`,
   `token_budget=20_000`.

### Operator provisioning steps

1. For each persona that will post (e.g. `default`, `growth-bot-1`,
   `karafiel-es`), log in to <https://bsky.app/settings/app-passwords>
   under the persona's Bluesky account.
2. Generate a NEW app password (16 chars, displayed once). Treat it
   like an API token — rotate quarterly per
   `docs/SECRET_ROTATION_POLICY.md`.
3. Store the handle + app password as Vault secrets, sync to the
   `autoswarm` namespace K8s Secret used by the worker Deployment.
   Naming convention:
   - `BLUESKY_HANDLE_DEFAULT` = `madfam.bsky.social`
   - `BLUESKY_APP_PASSWORD_DEFAULT` = `xxxx-xxxx-xxxx-xxxx`
   - (uppercase + hyphens replaced with underscores)
4. Install the `bluesky` extra in the worker image:
   `pip install selva-tools[bluesky]` (pulls in `atproto>=0.0.46`).
5. Quote-posts, image attachments, and threading are explicitly out
   of scope for this v1; v2 will add them.

`X` (Twitter) parity is still tracked in ROADMAP. Bluesky's tech-
leaning audience fits Selva (B2B founders/CTOs) and Yantra4D
(technical maker community) — that's why we ship it before X.

## Contributing

1. Create a feature branch from `main`.
2. Use conventional commits: `feat(scope): description`, `fix(scope): description`.
3. Open a pull request -- CI must pass before merge.
4. Commits are enforced by commitlint via husky pre-commit hooks.

## License

AGPL-3.0
