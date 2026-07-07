# Port Assignments

This is the **single source of truth** for service ports, public domains,
and health endpoints across local dev, container builds, and production
deployments. README.md, ECOSYSTEM.md, AGENTS.md, and other docs must
**reference this file** — do not redefine ports or probe paths elsewhere.

## Local development (host network)

| Port | Service | Notes |
|------|---------|-------|
| 4300 | nexus-api | FastAPI |
| 4301 | office-ui | Next.js |
| 4302 | admin | Next.js |
| 4303 | colyseus | Game state |
| 4304 | gateway | Heartbeat daemon (HTTP health + metrics) |
| 4305 | workers | Worker health + metrics |
| 4306 | inference-gateway | OpenAI-compatible /v1 proxy (RFC 0034 P2 extraction) |
| 5432 | PostgreSQL | Local dev (`make docker-dev`) |
| 6379 | Redis | Local dev (`make docker-dev`) |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Container ports (k8s)

These are the ports each service binds to **inside** the container in
production and staging. Selva uses the same numeric ports in k8s as in
local dev (except office-ui/admin, which bind 3000 in-container while
dev maps them to host 4301/4302). Cloudflare Tunnel routes the public
domain to the ClusterIP service on the container port.

| Container | Port | Service |
|-----------|------|---------|
| nexus-api | 4300 | FastAPI |
| office-ui | 3000 | Next.js |
| admin | 3000 | Next.js |
| colyseus | 4303 | Colyseus game server |
| gateway | 4304 | Heartbeat daemon (HTTP health + metrics) |
| workers | 4305 | LangGraph workers (health + metrics) |

Evidence: `infra/k8s/production/*.yaml`, `enclii.yaml`, `apps/nexus-api/nexus_api/config.py` (`port: 4300`).

## Public domains

| Domain | Routes to | Container port |
|--------|-----------|----------------|
| api.selva.town | selva-nexus-api | 4300 |
| app.selva.town | selva-office-ui | 3000 |
| admin.selva.town | selva-admin | 3000 |
| ws.selva.town | selva-colyseus | 4303 |
| gw.selva.town | selva-gateway (health/metrics) | 4304 |

Staging mirrors with a `staging-` prefix (`staging-api.selva.town`, etc.)
once DNS and secrets are provisioned — see `infra/k8s/overlays/staging/`
and Pattern B promotion notes in [AGENTS.md](../AGENTS.md).

## Health and readiness endpoints

| Service | Liveness | Readiness | Notes |
|---------|----------|-----------|-------|
| nexus-api | `GET /health` or `GET /api/v1/health/health` | `GET /api/v1/health/ready` | Root `/health` is the Enclii status URL; `/api/v1/health` alone returns 404 |
| colyseus | `GET /health` | same | |
| gateway | `GET /health` on :4304 | same | HTTP endpoint (not exec-only) |
| office-ui | `GET /api/health` | same | per `enclii.yaml` |
| admin | `GET /api/health` | same | per `enclii.yaml` |
| workers | `GET /health` on :4305 | same | internal only |

Additional nexus-api diagnostics (all under `/api/v1/health/`): `rls-status`,
`consent-ledger-grants`, `dlq-stats`, `queue-stats`, `pool-stats`.

## OpenAPI / Swagger

| Environment | Swagger UI | OpenAPI JSON |
|-------------|------------|--------------|
| development / staging | `GET /api/v1/docs` | `GET /api/v1/openapi.json` |
| production | disabled | disabled |

Production disables docs exposure (`environment=production` in
`apps/nexus-api/nexus_api/main.py`, audit H9).
