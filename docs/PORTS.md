# Port Assignments

This is the **single source of truth** for service ports across local
dev, container builds, and production deployments. CLAUDE.md and
README.md should reference this document; do not redefine ports
elsewhere.

## Local development (host network)

| Port | Service | Notes |
|------|---------|-------|
| 4300 | nexus-api | FastAPI |
| 4301 | office-ui | Next.js |
| 4302 | admin | Next.js |
| 4303 | colyseus | Game state |
| 4304 | gateway | Heartbeat daemon (health + metrics) |
| 4305 | workers | Worker health + metrics |
| 5432 | PostgreSQL | Local dev (`make docker-dev`) |
| 6379 | Redis | Local dev (`make docker-dev`) |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Container ports (k8s)

These are the ports each service binds to **inside** the container in
production. The container port is independent of the host-side dev port;
Cloudflare Tunnel routes the public domain to the ClusterIP service on
the container port.

| Container | Port | Service |
|-----------|------|---------|
| nexus-api | 8000 | FastAPI inside container |
| office-ui | 3000 | Next.js inside container |
| admin | 3001 | Next.js inside container |
| colyseus | 2567 | Game server inside container |
| gateway | 4304 | Health + metrics (same as dev) |
| workers | 4305 | Health + metrics (same as dev) |

## Public domains

| Domain | Routes to | Container port |
|--------|-----------|----------------|
| api.selva.town | selva-nexus-api | 8000 |
| app.selva.town | selva-office-ui | 3000 |
| admin.selva.town | selva-admin | 3001 |
| ws.selva.town | selva-colyseus | 2567 |
| gw.selva.town | selva-gateway (health/metrics only) | 4304 |

Staging mirrors with `staging-` prefix (`staging-api.selva.town`, etc.) —
see `infra/k8s/overlays/staging/` and the Pattern B promotion notes in
[CLAUDE.md](../CLAUDE.md).
