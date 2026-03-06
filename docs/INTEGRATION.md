# MADFAM Ecosystem Integration

AutoSwarm Office integrates with three sibling MADFAM platform services:
Janua (authentication), Dhanam (billing), and Enclii (deployment).

## Janua Auth Setup

Janua is the MADFAM platform's OpenID Connect identity provider. AutoSwarm Office
delegates all authentication to Janua -- never implement custom auth logic.

### OIDC Client Configuration

Register an OIDC client in Janua for AutoSwarm Office:

| Setting | Value |
|---------|-------|
| Client ID | `autoswarm-office` |
| Grant Types | `authorization_code`, `refresh_token` |
| Redirect URIs | `http://localhost:4301/api/auth/callback/janua` (dev) |
| Post-Logout URIs | `http://localhost:4301` (dev) |
| Scopes | `openid`, `profile`, `email` |

### Environment Variables

```bash
JANUA_ISSUER_URL=https://auth.madfam.io
JANUA_CLIENT_ID=autoswarm-office
JANUA_CLIENT_SECRET=<from Janua admin console>
NEXT_PUBLIC_JANUA_URL=https://auth.madfam.io
```

### Next.js Middleware (Office UI)

The Office UI uses Next.js middleware at `apps/office-ui/src/middleware.ts` to
intercept requests and validate the Janua session cookie. Unauthenticated requests
to protected routes are redirected to the Janua login page.

### FastAPI Middleware (Nexus API)

The Nexus API validates Janua-issued JWTs on every protected endpoint via the
`get_current_user` dependency in `apps/nexus-api/src/auth.py`. The dependency:

1. Extracts the Bearer token from the `Authorization` header.
2. Fetches the Janua JWKS from `{JANUA_ISSUER_URL}/.well-known/jwks.json` (cached).
3. Validates the token signature, expiry, issuer, and audience claims.
4. Returns the decoded JWT payload (sub, email, roles).

### JWT Claims

Janua tokens include these claims used by AutoSwarm:

| Claim | Usage |
|-------|-------|
| `sub` | User identifier, used as the primary key for user-scoped data |
| `email` | Display and notification purposes |
| `roles` | Array of roles; `admin` grants full access to all endpoints |
| `org_id` | Organization identifier for multi-tenant data isolation |

For the full Janua API surface, read the `llms-full.txt` file in the Janua repository.

## Dhanam Billing

Dhanam is the MADFAM platform's billing and subscription management service.
AutoSwarm uses Dhanam to enforce compute token budgets and tier-based feature gates.

### SDK Installation

The Nexus API communicates with Dhanam via its Python SDK or direct HTTP calls:

```bash
# In apps/nexus-api
uv add dhanam-sdk
```

For the Office UI billing dashboard:

```bash
# In apps/office-ui
pnpm add @dhanam/billing-sdk
```

### Configuration

```bash
DHANAM_API_URL=https://api.dhan.am
DHANAM_WEBHOOK_SECRET=<from Dhanam dashboard>
```

### Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/subscriptions/{org_id}` | GET | Fetch current subscription tier and status |
| `/v1/usage/{org_id}` | GET | Retrieve compute token usage for the billing period |
| `/v1/subscriptions/{org_id}/upgrade` | POST | Initiate a tier upgrade (redirects to Dhanam checkout) |
| `/v1/webhooks` | POST | Receive billing events (payment success, subscription change) |

### Subscription Tiers

| Tier | Max Agents | Max Departments | Daily Compute Tokens | Max Concurrent Tasks |
|------|-----------|----------------|---------------------|---------------------|
| starter | 5 | 2 | 500 | 2 |
| professional | 20 | 8 | 5000 | 10 |
| enterprise | unlimited | unlimited | 50000 | 50 |

### Webhook Verification

Dhanam signs webhook payloads with HMAC-SHA256 using `DHANAM_WEBHOOK_SECRET`. The
billing router at `apps/nexus-api/src/routers/billing.py` verifies this signature
before processing any webhook event.

For the full Dhanam API surface, read the `llms-full.txt` file in the Dhanam repository.

## Enclii Deployment

Enclii is the MADFAM platform's deployment orchestration layer. It watches for
container image pushes to GHCR and manages ArgoCD-based rollouts.

### Configuration File

The `.enclii.yml` at the project root defines three services:

| Service | Dockerfile | Port | Domain |
|---------|-----------|------|--------|
| `autoswarm-nexus-api` | `infra/docker/Dockerfile.nexus-api` | 4300 | `api.autoswarm.madfam.io` |
| `autoswarm-office-ui` | `infra/docker/Dockerfile.office-ui` | 3000 | `office.autoswarm.madfam.io` |
| `autoswarm-colyseus` | `infra/docker/Dockerfile.colyseus` | 4303 | `colyseus.autoswarm.madfam.io` |

### Deployment Pipeline

1. CI passes on the `main` branch.
2. The `deploy-enclii.yml` GitHub Actions workflow builds and pushes Docker images
   to `ghcr.io/madfam-org/autoswarm-*`.
3. The workflow POSTs a lifecycle callback to `https://api.enclii.dev/v1/callbacks/lifecycle-event`
   with the commit SHA and image tags.
4. Enclii receives the callback and updates the ArgoCD Application manifests in the
   MADFAM infrastructure repository.
5. ArgoCD detects the manifest change and performs a rolling update across the
   Kubernetes cluster.

### Health Checks

Each service exposes health and readiness endpoints that Enclii and Kubernetes use
for zero-downtime deployments:

| Service | Health | Readiness |
|---------|--------|-----------|
| nexus-api | `GET /api/v1/health` | `GET /api/v1/ready` |
| office-ui | `GET /api/health` | `GET /api/health` |
| colyseus | `GET /health` | `GET /health` |

### Autoscaling

All services are configured with horizontal pod autoscaling in `.enclii.yml`:

- **nexus-api**: 2-6 replicas, target 70% CPU
- **office-ui**: 2-8 replicas, target 70% CPU
- **colyseus**: 1 replica (stateful WebSocket connections; scale via Colyseus rooms)

### Secrets

Secrets are managed via Kubernetes SealedSecrets. The template is at
`infra/k8s/production/sealed-secret-template.yaml`. Required secrets:

- `database-url` -- PostgreSQL connection string
- `redis-url` -- Redis connection string
- `janua-client-secret` -- Janua OIDC client secret
- `dhanam-webhook-secret` -- Dhanam webhook HMAC key
- `anthropic-api-key` -- Anthropic API key for Claude inference
- `openrouter-api-key` -- OpenRouter API key for model routing

For the full Enclii API surface, read the `llms-full.txt` file in the Enclii repository.
