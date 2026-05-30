# MADFAM Ecosystem Integration

AutoSwarm Office integrates with three sibling MADFAM platform services:
Janua (authentication), Dhanam (billing), and Enclii (deployment).

**North-star orchestration plan:** [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md)
(cross-service Phases 0–6). **Tulana → Selva → Phynd CRM** campaign path:
[TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](./TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md)
(Program Phase 2).

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
JANUA_ISSUER_URL=https://auth.example.com
JANUA_CLIENT_ID=autoswarm-office
JANUA_CLIENT_SECRET=<from Janua admin console>
NEXT_PUBLIC_JANUA_URL=https://auth.example.com
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
**All Stripe and point-of-sale flows route through Dhanam** — Selva never
accepts direct Stripe webhooks in production when `BILLING_VIA_DHANAM=true`
(default). Dhanam normalizes provider events and pushes tier/subscription
updates to Selva.

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
DHANAM_API_URL=https://billing.example.com
DHANAM_WEBHOOK_SECRET=<from Dhanam dashboard>
BILLING_VIA_DHANAM=true  # default; set false only for break-glass direct Stripe
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
billing router at `apps/nexus-api/nexus_api/routers/billing.py` verifies this signature
before processing any webhook event. Processing is delegated to
`apps/nexus-api/nexus_api/services/billing_sync.py`.

| Dhanam event `type` | Selva action |
|---------------------|--------------|
| `subscription.created` / `subscription.updated` | Update `tenant_configs` tier/status; cache daily limit in Redis |
| `subscription.cancelled` / `subscription.deleted` | Mark subscription `cancelled` |
| `invoice.paid` | Clear overage counter; emit `billing.invoice_paid` |
| `invoice.payment_failed` | Mark `past_due`; emit `billing.payment_failed` |

Payload `data` must include `org_id` and normalized `tier` (Dhanam resolves Stripe
price IDs — do not configure `STRIPE_PRICE_TO_TIER_MAP` in Selva when billing via Dhanam).

**Legacy break-glass:** `/api/v1/stripe/webhook` remains for emergencies when
`BILLING_VIA_DHANAM=false` and `STRIPE_WEBHOOK_SECRET` is set.

For the full Dhanam API surface, read the `llms-full.txt` file in the Dhanam repository.

## Enclii Deployment

Enclii is the MADFAM platform's deployment orchestration layer. It watches for
container image pushes to GHCR and manages ArgoCD-based rollouts.

### Configuration File

The `.enclii.yml` at the project root defines three services:

| Service | Dockerfile | Port | Domain |
|---------|-----------|------|--------|
| `autoswarm-nexus-api` | `infra/docker/Dockerfile.nexus-api` | 4300 | `api.selva.town` |
| `autoswarm-office-ui` | `infra/docker/Dockerfile.office-ui` | 3000 | `selva.town` |
| `autoswarm-colyseus` | `infra/docker/Dockerfile.colyseus` | 4303 | `ws.selva.town` |

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

| Service | Health | Readiness | Detail |
|---------|--------|-----------|--------|
| nexus-api | `GET /api/v1/health/health` | `GET /api/v1/health/ready` | `GET /api/v1/health/detail` |
| office-ui | `GET /api/health` | `GET /api/health` | -- |
| colyseus | `GET /health` | `GET /health` | -- |
| gateway | `GET /health` on :4304 | `GET /health` on :4304 | Heartbeat metrics in JSON body |

Health endpoints are exempt from rate limiting.

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

## Tulana campaign orchestration (Phase 2)

Selva imports Tulana SKU campaign packs and ranks them before agent dispatch.
Contract: [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](./TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md).

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /api/v1/campaigns/import-tulana-pack` | Bearer (Janua JWT) | Validate Tulana export JSON, rank SKUs, optional `dispatch_tasks` |

Implementation: `apps/nexus-api/nexus_api/routers/campaigns.py`,
`schemas/tulana_campaign.py`, `services/tulana_campaign.py`.
Tests: `apps/nexus-api/tests/test_tulana_campaign_import.py`.

Tulana webhook outcomes (pricing apply) use existing `TULANA_API_URL` +
`tulana_selva_webhook_secret` settings — see `services/pricing_apply.py`.
