# Selva Office Agent Operating Guide

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


<!-- MADFAM-AGENTS-CANONICAL v1 -->

This is the canonical instruction file for Claude, Codex, and any other LLM
agent working in this repository. `CLAUDE.md` is kept only as a compatibility
redirect and should not become the source of truth again.

## Required operating doctrine

- Selva Office is an agent and inference platform. Treat tool execution,
  worker dispatch, autonomous actions, social posting, email or marketing
  send, GitHub writes, database writes, payment/webhook calls, provider API
  calls, load tests, deploys, promotions, and rollbacks as side-effectful
  operations. Do not run them against production, tenant, customer, or shared
  data unless the user explicitly requests the action and names the target
  environment.
- Examples and templates must stay placeholder-only. Do not add provider keys,
  worker tokens, org configs, customer data, prompts, tool payloads, social
  account credentials, webhooks, or GitHub tokens to repository files or MCP
  memory.
- Read this file before making repo changes.
- Prefer existing repo conventions, scripts, and docs over introducing new
  patterns.
- Preserve user work and never revert unrelated changes.
- Treat production operations as Enclii-first: use Enclii web, API, or CLI for
  provisioning, deployment, observability, domains, secrets, provider
  operations, scaling, rollback, and remediation.
- Use direct `kubectl`, `helm`, SSH, provider CLIs/APIs, `docker exec`, or
  direct container access only for platform bootstrap or documented break-glass
  emergencies when Enclii is unavailable or lacks an implemented adapter.
- Record any missing Enclii adapter gap instead of normalizing raw production
  access in docs or runbooks.

## Repo entrypoints

- `README.md`
- `ECOSYSTEM.md`
- `ROADMAP.md`
- `docs/AUTONOMOUS_OPERATIONS_PROGRAM.md` — north-star plan (Phases 0–6)
- `docs/OPERATOR_BACKLOG.md` — operator-gated items
- `docs/`
- `infra/`
- `.github/workflows/`

## LLM context files

- `llms.txt` is the compact context index.
- `llms-full.txt` is the durable full-context map and operating contract.
- `AGENTS.md` is canonical for agent instructions.
- `CLAUDE.md` redirects here for Claude compatibility.

## Maintenance

Regenerate or repair these files with
`internal-devops/scripts/sync-agent-docs.py` from the labspace ecosystem.

---

## Legacy CLAUDE.md guidance imported on 2026-05-13

<!-- BEGIN LEGACY_CLAUDE_IMPORT -->

# CLAUDE.md -- Selva Office

> **Picking this back up after a break?** Start with
> [docs/OPERATOR_BACKLOG.md](docs/OPERATOR_BACKLOG.md) for the
> 12 currently-blocked operator items (Tier-ordered) + the
> recommended reading order at the bottom. After that, the
> ["Patterns Added in v2.3.0"](#patterns-added-in-v230-operator-must-know)
> section below is the most current operator/contributor reference.

## Pricing & PMF Anchoring

- **Pricing source-of-truth**: `infra/pricing/selva-tiers.json` (canonical, schema-validated against `infra/pricing/schema.json`). Derived from `internal-devops/decisions/2026-04-25-tulana-ecosystem-pricing.md` (the human-readable upstream). Selva tiers (Tulana v0.1, MXN/hr): Maker Pack 85 / Studio Pack 170 / Enterprise Pack 255 — confidence **medium**. Dhanam subscription daily limits (starter=1000, professional=5000, enterprise=25000) ship in the same JSON. The Python loader is `apps/nexus-api/nexus_api/billing_tiers.py`; the CI drift gate is `apps/nexus-api/tests/test_pricing_codification.py` (asserts loader + JSON + CLAUDE.md + emergency fallback all agree). Adjacent ecosystem bundles (Founder/Operator/Flywheel, USD/mo) are still in `apps/office-ui/src/app/bundles/page.tsx:60-117` — TS-side codification follow-up tracked in ROADMAP.
- **PMF measurement**: per RFC 0013, NPS + Sean Ellis + retention via `@madfam/pmf-widget` → Tulana `/v1/pmf/*` endpoints. Composite PMF Score informs price moves + sunset decisions.

## Patterns Added in v2.3.0 (operator must know)

Three new patterns shipped 2026-05-04 that operators / contributors need
to know about. Each has its own dedicated section below; this is the
quick-reference index.

- **Idempotency-Key on mutation endpoints** — 10 mutations are now
  replay-safe. Use `Depends(get_idempotency_context)` on any new
  mutation endpoint where double-execution would be costly. Pattern in
  `apps/nexus-api/nexus_api/idempotency.py` docstring; adoption
  examples in `routers/swarms.py:dispatch_task` and
  `routers/marketplace.py:install_skill`. Test pattern in
  `tests/test_idempotency_tier_1_adoption.py`.

- **`tenant_session(org_id)` helper** for non-FastAPI database access
  paths (WS handlers, A2A bridge, audit middleware). MUST be used
  instead of bare `async_session_factory()` — the latter leaves
  `app.current_org_id` unset and post-RLS-strict-mode that means
  "queries succeed today but break the day strict mode lands." See
  `apps/nexus-api/nexus_api/database.py:tenant_session` docstring.
  For genuine cross-tenant operator queries (reap-stale,
  fleet-wide reports), use `admin_session()` instead — it selects
  the BYPASSRLS connection pool.

- **PostgresSaver real lifecycle** — workers now persist LangGraph
  state across pod restarts. Worker → checkpoint write → pod kill →
  pod restart → graph resumes from checkpoint. Operator: ensure
  `DATABASE_URL` is reachable from worker pods. Init failure logs at
  ERROR (not WARNING) because falling back to `MemorySaver` silently
  is the bug we just closed.

## Security Posture (v2.2.x — post-remediation, augmented in v2.3.0)

Quick-reference for new contributors. Each bullet group is an invariant the
remediation enforces — break one and you break a tenancy/safety
boundary. Followups tracked in ROADMAP.md.

- **Worker → API auth**: every worker call sends `X-Selva-Tenant-Org: <org_id>`
  alongside the `Authorization: Bearer <WORKER_API_TOKEN>` header. The header
  is the sole source of org scope for worker-authenticated requests — there
  is no `"madfam-default"` fallback anymore. Missing header resolves to
  `org_id="platform"` (MADFAM-only). Use the helper, never hand-craft headers:

  ```python
  headers = get_worker_auth_headers(org_id=task.org_id)
  ```

  Reader: `apps/nexus-api/nexus_api/auth.py:136-160`. Writer:
  `apps/workers/selva_workers/auth.py`.

- **Tenant scoping invariants** (REST + WS):
  - REST endpoints that mutate (`POST /api/v1/chat/messages`,
    `POST /api/v1/events`, `POST /api/v1/approvals/...`) MUST derive
    `org_id` from `Depends(get_current_user)` or `Depends(get_tenant)` and
    MUST reject any `org_id` supplied in the request body. Read endpoints
    scope queries by the JWT-derived `org_id`.
  - WebSocket endpoints accept `?token=<jwt>` as a query param (browsers
    cannot set custom headers on `WebSocket` upgrade). Workers connect with
    both `?token=<worker-jwt>` and `?org_id=<uuid>` because the
    `X-Selva-Tenant-Org` header is stripped during the WS handshake.

- **Outbound email lockdown**: `SendEmailTool` and `SendMarketingEmailTool`
  no longer accept `user_email`, `user_name`, or `agent_slug` from the LLM.
  The From: header is server-derived from `tenant_configs.brand_name` and
  `tenant_identities.primary_contact_email`, fetched via
  `_fetch_tenant_identity(org_id)` → `GET /api/v1/onboarding/tenant-identity`.
  The only LLM-controllable identity field is `agent_role`, constrained to
  the server-side allow-list `{sales, support, growth, ops, research}`
  (see `_AGENT_ROLE_ALLOWLIST` in `email_tools.py`). Any other value raises
  `ValueError` before send. `SendNotificationTool` with `channel="email"`
  delegates to `SendEmailTool.execute()` so it inherits the same voice-mode,
  consent, sanitization, and identity gates — never call `Resend` directly
  from a tool.

- **Webhook signature verification (fail-closed)**: `_verify_hmac` returns
  `False` on empty/missing secret. Each handler MUST check the result and
  return `503` when the secret env var is unset and `401` when the
  signature does not match. Three handlers fully hardened in v2.2.x
  (Discord, WhatsApp, generic). DO NOT skip the check just because the
  secret is empty in your local env — that is the regression we just fixed.
  Remaining 12 handlers tracked in ROADMAP.md.

- **Consent ledger integrity**: `signature_sha256` is now
  `hmac.new(CONSENT_LEDGER_SIGNING_SECRET, payload, sha256).hexdigest()`,
  not plain SHA-256. Append-only is enforced at the database level by
  migration 0018 (REVOKE UPDATE/DELETE on `selva_app`). Verify the
  invariant at runtime with `GET /api/v1/health/consent-ledger-grants` —
  returns `{invariant_holds, can_insert, can_update, can_delete}`. Old
  rows signed with plain SHA-256 (pre-v2.2.x) intentionally fail HMAC
  verification; that is the audit boundary, do not "fix" it by re-signing.

- **Artifact storage containment**: `LocalFSStorage._resolve_safe(path)`
  rejects any path that resolves outside `_base` (path traversal /
  symlink escape). `RetrieveArtifactTool` validates the content-hash
  shape `^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$` upfront, before
  touching the filesystem. Never bypass either check — they are the
  only thing between a malicious tool argument and arbitrary file read.

- **Outbound HTTP (SSRF + DNS-rebinding)**: any tool that takes an
  attacker-controllable URL MUST go through
  `selva_tools.builtins.http_tools._build_safe_request_kwargs`. It
  resolves the URL once via `socket.getaddrinfo`, rejects private/loopback
  IPs, then connects by IP with the original Host header preserved and
  SNI hostname overridden so TLS verification still works. Pair with
  `httpx.AsyncClient(trust_env=False)` to neutralize the `HTTP_PROXY`
  env var as an exfil vector. Calling `httpx` directly with a
  user-supplied URL is a security regression.

- **New env vars** (v2.2.x):
  - `WORKER_API_TOKEN` — Settings refuses the literal `dev-bypass` when
    `ENVIRONMENT=production`.
  - `CONSENT_LEDGER_SIGNING_SECRET` — Settings refuses
    `dev-default-CHANGE-ME` in production.
  - `COLYSEUS_SERVICE_TOKEN` — when unset, chat persistence (Colyseus
    → nexus-api) skips silently rather than 401-looping.
  - `events_ws_rate_limit` / `events_ws_rate_window_seconds`
    (default 30 / 60.0).
  - `approvals_ws_rate_limit` / `approvals_ws_rate_window_seconds`
    (default 30 / 60.0).
  - `dlq_recent_limit` (default 10) — caps payload size of
    `/api/v1/health/dlq-stats`.
  - Worker-side: `redis_block_timeout_ms` (default 5000),
    `event_emit_timeout_seconds` (default 3).

- **Cross-language single-source-of-truth**: `OFFICE_BOUNDS` and
  `WORLD_*` constants live in `packages/shared-types/src/world.ts` —
  consumed by both Colyseus (TS) and any Python service that needs
  them via the generated bindings. Dhanam tier limits + Tulana hourly
  packs live in `infra/pricing/selva-tiers.json` (canonical, schema-
  validated against `infra/pricing/schema.json`); `billing_tiers.py`
  loads from JSON. Do not duplicate; CI drift gate
  (`tests/test_pricing_codification.py`) catches if you do.

## Patterns Added in v2.3.0 — full reference

### Idempotency-Key on mutation endpoints

Use on POST endpoints whose effects are side-effecting + non-trivial
to undo. Adopt via:

```python
from ..idempotency import IdempotencyContext, get_idempotency_context

@router.post("/your-endpoint", response_model=YourResponse)
async def your_handler(
    body: YourRequest,
    db: AsyncSession = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
    idem: IdempotencyContext = Depends(get_idempotency_context),
) -> YourResponse:
    # 1. Replay short-circuit
    if idem.is_replay and idem.cached is not None:
        return YourResponse.model_validate(idem.cached)

    # 2. Do the work — every side effect must complete before save()
    # ... mutation logic ...
    response = YourResponse(...)

    # 3. Cache only on success — 4xx/5xx HTTPException short-circuits
    #    past this line, so failed paths don't lock out retries
    await idem.save(response.model_dump(mode="json"))
    return response
```

Key shape: `selva:idem:<org_id>:<method>:<path>:<key>` — org-
scoped (cross-tenant cache leak prevention) + method+path scoped
(same key against /a vs /b are different operations per RFC 9457).
24h TTL. No-op when `Idempotency-Key` header absent (caller opt-in).

Currently adopted on: `swarms.dispatch`, `approvals.{approve,deny}`,
`onboarding.voice-mode`, `marketplace.install`, `calendar.connect`,
`maps.{create,import}`, `workflows.{create,import}`. See PRs #127,
#141, #142.

### `tenant_session(org_id)` for non-FastAPI DB paths

Anywhere code opens a DB session OUTSIDE the request flow (WS
handlers, background tasks, audit middleware), use `tenant_session`
not `async_session_factory()` directly:

```python
from ..database import tenant_session

async with tenant_session(org_id="org-abc") as db:
    # session has app.current_org_id set; RLS policies pass
    event = TaskEvent(org_id="org-abc", ...)
    db.add(event)
    # commit happens on context exit
```

For genuine cross-tenant operator queries (reap-stale, fleet-wide
reports, cross-org analytics), use `admin_session()` instead — it
selects the BYPASSRLS connection pool (`database_admin_url` env var
sets the BYPASSRLS-role connection string; falls back to main pool
when unset for dev / SQLite test paths).

The 5 sites originally identified by the RLS Phase 1.5 audit
(audit middleware, A2A bridge `_dispatch_a2a_task` +
`_get_a2a_task_status`, WS initial-batch in
`approvals.py:454/523`, WS initial-batch in `events.py:345`) all
migrated in PR #126. Bare `async_session_factory()` MUST NOT be
reintroduced — the import-shape regression tests in
`tests/test_tenant_session_helper.py` catch it.

### RLS strict mode + `admin_session()`

Migration 0028 (PR #134) tightened the Phase 1 permissive policy
(`IS NULL OR = '' OR = $org`) to strict
(`current_setting(...) = $org OR current_setting(...) = 'platform'`)
+ applied `FORCE ROW LEVEL SECURITY` on all 18 tenant tables. Net
effect: a session that doesn't `SET LOCAL app.current_org_id = ...`
sees ZERO rows from tenant tables.

Two new env vars:
- `database_admin_url` — connection string for the BYPASSRLS role
  (`app_admin`). When unset, `admin_session()` falls back to the
  main pool (acceptable for SQLite tests; NOT for production where
  RLS is FORCEd). Operator: provision the `app_admin` role per
  migration 0028's docstring + set this env in production.
- `db_admin_pool_size` (default 2) — small pool because
  cross-tenant ops are rare.

Operator runtime check: `GET /api/v1/health/rls-status` returns
`{strict_mode_enabled, policies, force_rls_tables, app_admin_role_present, dialect}`.
Returns 503 when strict mode isn't enabled — useful in alert
chains to detect "we accidentally rolled back to permissive."

### PostgresSaver real lifecycle

Worker checkpoint persistence — closes the silent-state-loss bug
where `PostgresSaver.from_conn_string()` was being called as a
factory (it's a `@contextmanager`) so `MemorySaver` was used in
practice. Worker pod kill mid-graph used to lose state; now it
resumes from the checkpoint.

`apps/workers/selva_workers/checkpointer.py` opens a
`psycopg_pool.ConnectionPool` (min=1, max=4) wired into
`PostgresSaver(conn=pool)`. `close_checkpointer()` is called from
`__main__.py:main()` after the graceful drain so DB connections
are released cleanly on SIGTERM.

Init failure logs at **ERROR** (not WARNING) — Postgres-unreachable
worker is degraded; ops needs to page on it. Falling back to
MemorySaver silently is the regression we just closed.

### Consent-ledger per-period HMAC key tracking (PR #145)

`CONSENT_LEDGER_SIGNING_SECRET` is now safe to rotate quarterly.
Previously the env-level key was the single source for HMAC
verification — rotating invalidated every pre-rotation row's
signature forever. Per `docs/SECRET_ROTATION_POLICY.md` §6, the
quarterly cycle USED to skip this secret. After PR #145 it doesn't.

Mechanism:
- Migration 0030 creates `consent_ledger_signing_keys` table
  (`key_version` PK, `key_value`, `created_at`, `retired_at`,
  `is_current`). Postgres partial unique index on
  `is_current=true` enforces "exactly one current key" at the DB
  layer.
- `consent_ledger.signing_key_version` FK column means every row
  carries its signing key's version. Pre-0030 rows backfill to v1.
- `compute_signature()` insert path uses the current key + stamps
  `signing_key_version`. Verify path looks up the row's version,
  recomputes HMAC under that version. Old keys verify old rows
  forever.
- `POST /api/v1/admin/consent-ledger/promote-key` (admin/platform
  role-gated) atomically retires old + inserts new key. Emits
  `consent_ledger.key_promoted` audit event with payload
  `{new_key_version, previous_key_version, actor_sub, actor_ip}`
  — never the key value.
- `scripts/rotate-secret.sh consent-ledger-signing` calls
  promote-key FIRST then patches the K8s Secret — aborts cleanly
  on promote-key failure (no half-applied state). Required env
  vars: `NEXUS_API_URL`, `NEXUS_ADMIN_TOKEN`.
- `GET /api/v1/health/consent-ledger-grants` extended to report
  signing key count + current `key_version` (NEVER the value).

Bootstrap: migration 0030 reads `CONSENT_LEDGER_SIGNING_SECRET`
env at migration time. If set to a real value (not the
`dev-default-CHANGE-ME` sentinel), v1 row gets that value with
`is_current=true`. Otherwise v1 row inserted with empty value +
`is_current=false`, so the system stays runnable but `_record_consent`
fails-closed with HTTP 503 until an admin promotes a real key.

### Idempotency + tenant_session adoption checklist for new mutation endpoints

When adding a new `POST` / `PUT` / `PATCH` / `DELETE` endpoint that
modifies tenant-scoped state, the PR MUST:

- [ ] Use `Depends(get_db)` (FastAPI request flow) OR
      `tenant_session(org_id)` (non-request paths). Never bare
      `async_session_factory()`.
- [ ] Emit a `TaskEvent` via `emit_event_db` for state changes that
      should be auditable (see `docs/AUDIT_TRAIL_GAP_ANALYSIS.md` for
      the canonical pattern; CDC RFC 0019 will eventually replace
      manual emit).
- [ ] If the operation is side-effecting + costly to repeat
      (dispatching a task, charging a customer, sending an email),
      adopt `Depends(get_idempotency_context)` per the pattern above.
- [ ] Classify into Tier 1 / Tier 2 / Tier 3 per `docs/SLOS.md` §1
      and add an SLI row to §4.
- [ ] If the endpoint hits a sibling service (Janua / Dhanam /
      Karafiel / etc.), use `selva_observability.propagation` so the
      W3C trace context flows (PR #137 wired this; happens for free
      via `get_worker_auth_headers` and `_build_safe_request_kwargs`).

## Deployment Pipeline (dev → staging → prod)

selva-office is the **Phase 4** target for the 3-tier pipeline
defined in [internal-devops/rfcs/0001-dev-staging-prod-pipeline.md](https://github.com/madfam-org/internal-devops/blob/main/rfcs/0001-dev-staging-prod-pipeline.md).

**Current state (PP.4 shipped):** Staging now lives at
`infra/k8s/overlays/staging/` as a Kustomize overlay of the prod
canonical base (`infra/k8s/production/`), digest-pinned, reconciled
by the `selva-office-staging` ArgoCD Application
(`infra/argocd/staging.yaml`). Promote + rollback are manual workflows
(Pattern B — agent code that touches prod customer data).

See [docs/PP_4_STAGING_AUDIT.md](docs/PP_4_STAGING_AUDIT.md) for the
row-by-row gap analysis.

### Flow

| Action | Trigger | Workflow | Target |
|---|---|---|---|
| Build + deploy all 6 services to staging | push to `main` | `.github/workflows/staging-deploy.yml` | `selva-staging` namespace |
| Build + deploy to prod (legacy, still live) | push to `main` | `.github/workflows/deploy.yml` | `selva` namespace |
| Promote one or all services to prod | manual `workflow_dispatch` | `.github/workflows/promote-to-prod.yml` | `infra/k8s/overlays/production/kustomization.yaml` |
| Rollback prod | manual `workflow_dispatch` | `.github/workflows/rollback-prod.yml` | `infra/k8s/overlays/production/kustomization.yaml` |

Staging and legacy prod run side-by-side during the 14-day soak. PP.5
will cut over the prod ArgoCD Application's `path:` from
`infra/k8s/production` to `infra/k8s/overlays/production` and
decommission the `commit-digests` stage of `deploy.yml`.

### Promotion rules (Pattern B — manual gate)

- Promotion is a **pointer update**, never a rebuild.
- Promote only after staging has soaked ≥30 min and the staging smoke
  passed (enforced by `promote-to-prod.yml` via git-log traversal of
  the staging overlay + `MIN_SOAK_MINUTES` repo var).
- selva-office is Pattern B because workers execute agent code
  that sends real customer emails (Resend), pushes real git branches
  (GitHub API), and calls Stripe/PhyndCRM/Dhanam in production.

### Rollback

- RTO target: <5 min.
- Trigger `rollback-prod.yml` with the target digest; defaults to the
  previous prod digest automatically (read from git history of the
  prod overlay).

### Staging guardrails (what MUST stay off)

- `AUTO_DISPATCH_ENABLED=false` on the gateway (heartbeat loop does
  not dispatch SwarmTasks → no autonomous emails, PRs, or webhooks)
- `FEATURE_STRIPE_MXN_LIVE=false` on workers (no live Stripe events)
- `FEATURE_VOICE_MODE_LIVE=false` on workers (voice-mode tool layer
  refuses sends anyway when `voice_mode` is NULL, but belt + braces)
- `FEATURE_REDDIT_BOT=false` on workers
- HPAs pinned to `maxReplicas=1` in staging (3 HPAs: nexus-api,
  office-ui, colyseus)
- Staging secrets (`selva-staging-secrets`,
  `selva-staging-llm-secrets`, `selva-staging-admin-auth`)
  provisioned in the `selva-staging` namespace — template at
  `infra/k8s/overlays/staging/staging-secrets-template.yaml`.

### Operator actions pending

- Register Janua staging OAuth client (`selva-office-staging`)
  with redirect URIs for `staging-admin.selva.town` and
  `staging.selva.town`.
- Provision the 3 staging Secrets per the bootstrap commands in
  `docs/PP_4_STAGING_AUDIT.md` § recommended ordering.
- Create Cloudflare DNS + tunnel routes for `staging-api.selva.town`,
  `staging.selva.town`, `staging-admin.selva.town`,
  `staging-ws.selva.town`, `staging-gw.selva.town`.
- `kubectl apply -f infra/argocd/staging.yaml` + sync.

## Quick Start (Local Dev)

```bash
# Prerequisites: Docker, Node 20+, pnpm 9+, Python 3.12+, uv

# 1. Clone and install
git clone <repo-url>
cd selva-office
make dev-full    # Installs deps, starts Docker, migrates, seeds, boots all services

# 2. Open the office
# Navigate to http://localhost:4301 (landing page)
# Click "Try Demo" for sandboxed demo, or "Sign In" → Dev Login → /office

# 3. (Optional) Enable LLM inference
# Add at least one API key to .env:
#   ANTHROPIC_API_KEY=sk-ant-...
#   or OPENAI_API_KEY=sk-...
# Then restart the worker: make worker

# 4. (Optional) Enable git push
# Set GITHUB_TOKEN in .env to a PAT with repo scope
```

## Route Structure

| Path | Auth | Purpose |
|------|------|---------|
| `/` | Public | Landing page |
| `/demo` | Public | Demo office with simulated agents |
| `/office` | Protected | Real office (main experience) |
| `/login` | Public | Dev bypass + Janua SSO |
| `/guest` | Public | Invite-based guest join |

## Critical Paths

- `apps/nexus-api/src/main.py` -- FastAPI application entry point
- `apps/office-ui/src/app/page.tsx` -- Landing page (server-rendered)
- `apps/office-ui/src/app/office/page.tsx` -- Office page (protected, live mode)
- `apps/office-ui/src/app/demo/page.tsx` -- Demo page (public, sandbox mode)
- `apps/office-ui/src/components/OfficeExperience.tsx` -- Shared office experience component
- `apps/colyseus/src/demo/DemoSimulator.ts` -- Demo agent simulation engine
- `apps/workers/selva_workers/__main__.py` -- Worker process entry (task status lifecycle)
- `apps/workers/selva_workers/task_status.py` -- Fire-and-forget task PATCH to nexus-api
- `apps/workers/selva_workers/auth.py` -- Centralized worker-to-API auth headers
- `apps/workers/selva_workers/prompts.py` -- Repo-context-aware LLM system prompts
- `apps/workers/selva_workers/learning.py` -- Post-task learning (experience, reflexion, bandit, stats)
- `apps/workers/selva_workers/event_emitter.py` -- Fire-and-forget event POST + Redis PUBLISH
- `apps/nexus-api/nexus_api/routers/events.py` -- Events REST API + WebSocket stream
- `apps/nexus-api/nexus_api/routers/metrics.py` -- Ops metrics dashboard aggregation API
- `apps/workers/selva_workers/graphs/coding.py` -- Coding graph (plan/implement/test/review/push)
- `apps/workers/selva_workers/graphs/base.py` -- Shared graph state, permission checks
- `packages/orchestrator/src/orchestrator.py` -- Swarm orchestration engine
- `packages/permissions/src/matrix.py` -- HITL permission matrix
- `packages/permissions/src/engine.py` -- Permission evaluation engine
- `packages/inference/madfam_inference/org_config.py` -- Org-level config (task types, model assignments, services)
- `packages/inference/madfam_inference/router.py` -- LLM model routing logic
- `packages/inference/madfam_inference/factory.py` -- Shared `build_router_from_env()` (worker + proxy)
- `apps/nexus-api/nexus_api/routers/inference_proxy.py` -- OpenAI-compatible `/v1/` proxy (ecosystem gateway)
- `apps/nexus-api/nexus_api/routers/intelligence.py` -- Intelligence config API
- `apps/nexus-api/nexus_api/routers/chat.py` -- Chat history persistence API
- `apps/nexus-api/nexus_api/routers/admin.py` -- Admin controls (kick, room config)
- `apps/colyseus/src/handlers/teleport.ts` -- Player teleport handler
- `packages/workflows/src/selva_workflows/compiler.py` -- YAML-to-LangGraph compiler
- `packages/workflows/src/selva_workflows/schema.py` -- Workflow definition models
- `packages/tools/src/selva_tools/registry.py` -- Tool registry (268 built-in tools; see `builtins/__init__.py:get_builtin_tools`)
- `packages/memory/src/selva_memory/store.py` -- Per-agent FAISS memory store
- `packages/tools/src/selva_tools/storage/local.py` -- Content-addressable artifact storage
- `packages/tools/src/selva_tools/builtins/artifact.py` -- Artifact management tools (save/retrieve/list)
- `packages/workflows/src/selva_workflows/nodes/batch.py` -- Batch processing node handler
- `packages/tools/src/selva_tools/builtins/image_analysis.py` -- Image analysis tool (multimodal)
- `apps/nexus-api/nexus_api/routers/marketplace.py` -- Skill marketplace CRUD API
- `packages/sdk/selva_sdk/client.py` -- Python SDK async/sync clients
- `packages/orchestrator/selva_orchestrator/bandit.py` -- Thompson Sampling agent selection
- `packages/orchestrator/selva_orchestrator/puppeteer.py` -- RL orchestrator
- `apps/workers/selva_workers/graphs/puppeteer.py` -- Puppeteer graph (decompose/assign/execute/aggregate/feedback)
- `apps/workers/selva_workers/graphs/meeting.py` -- Meeting notes graph (transcribe/summarize/extract/save)
- `packages/calendar/selva_calendar/` -- Google/Microsoft calendar adapters
- `apps/nexus-api/nexus_api/routers/maps.py` -- Map CRUD API
- `apps/nexus-api/nexus_api/routers/calendar.py` -- Calendar connection API
- `apps/office-ui/src/game/constants.ts` -- Centralized game-layer constants
- `apps/office-ui/src/lib/constants.ts` -- Shared UI-layer constants (event keys, reconnect delays)
- `apps/office-ui/src/lib/logger.ts` -- Dev-only logging wrapper (suppressed in production)
- `apps/nexus-api/nexus_api/routers/onboarding.py:tenant_identity` -- `GET /api/v1/onboarding/tenant-identity` returning the server-derived outbound identity (brand_name + primary_contact_email) for the email From: lockdown
- `apps/nexus-api/nexus_api/routers/health.py:consent_ledger_grants` -- `GET /api/v1/health/consent-ledger-grants` runtime audit of the migration-0018 REVOKE; returns `{invariant_holds, can_insert, can_update, can_delete}`
- `apps/nexus-api/nexus_api/billing_tiers.py` -- single source of truth for Dhanam tier limits (`TIER_DAILY_TASK_LIMIT`)
- `packages/shared-types/src/world.ts` -- single source of truth for world dimensions (`OFFICE_BOUNDS`, `WORLD_*`)
- `packages/tools/src/selva_tools/builtins/email_tools.py` -- `_AGENT_ROLE_ALLOWLIST`, `_fetch_tenant_identity()`, voice-mode + consent gates
- `packages/tools/src/selva_tools/builtins/http_tools.py` -- `_build_safe_request_kwargs` (SSRF + DNS-rebinding hardening)
- `packages/tools/src/selva_tools/storage/local.py:_resolve_safe` -- artifact path containment

## Outbound Voice Mode + Consent Ledger (v2.2.0)

- **Three legal modes**: `user_direct` (send as the user, no AI disclosure),
  `dyad_selva_plus_user` (co-branded "Selva on behalf of <user>"), and
  `agent_identified` (send from `<agent-slug>@selva.town`, explicit agent
  disclosure). Stored on `tenant_configs.voice_mode` (nullable — NULL means
  onboarding incomplete).
- **Append-only consent ledger**: Migration 0018 creates `consent_ledger`
  (id, org_id, user_sub, user_email, mode, clause_version, typed_confirmation,
  signer_ip, signer_user_agent, signature_sha256, created_at). UPDATE and
  DELETE are REVOKEd from the `selva_app` role at the database level —
  rows can only be appended. Replay `compute_signature()` in
  `routers/onboarding.py` to verify a row at audit time.
- **Onboarding API**: `GET /api/v1/onboarding/status`,
  `GET /api/v1/onboarding/voice-mode/preview/{mode}`,
  `POST /api/v1/onboarding/voice-mode` (first-run, 409 on second call),
  `PUT /api/v1/settings/outbound-voice` (change, appends new ledger row),
  `GET /api/v1/onboarding/tenant-identity` (server-resolved From: header
  inputs for the email tools),
  `PUT /api/v1/onboarding/tenant-identity` (tenant-side update of the
  outbound identity columns; emits `tenant_identity.updated` to
  `task_events`).
- **Outbound identity columns** (migration 0026): `tenant_configs.outbound_user_email`,
  `outbound_user_name`, `outbound_agent_slug` are first-class
  tenant-configurable fields. The GET tenant-identity endpoint prefers
  these over the legacy fallback chain (brand_name → razon_social →
  tenant_identities) so tenants can configure outbound identity from
  the office UI at `/settings/outbound-identity` without ops
  intervention. PUT validates email format + slug allow-list
  (sales/support/growth/ops/research) and forces `org_id` from the
  JWT.
- **Tool enforcement**: `SendEmailTool` and `SendMarketingEmailTool`
  fetch `voice_mode` via nexus-api `/api/v1/onboarding/status` before
  every send and refuse when NULL. `agent_identified` sends additionally
  verify SPF/DKIM/DMARC alignment on `selva.town` via
  `_spf_check.check_alignment()` (10-min TTL cache). Per-mode From
  header + HTML signature are built by `_email_signatures.build_identity()`.
- **Legal basis**: Clauses versioned as `voice-mode-v1.0`. Research
  informed by Mexico LFPDPPP 2025 amendments ("free/specific/informed"),
  GDPR Art.7 (clear affirmative action, distinguishable, withdrawable),
  CAN-SPAM (accurate From/Reply-To), California BOT Act SB-1001 (bot
  disclosure risk on `user_direct` for CA residents), CASL Canada (sender
  identification), LGPD Brazil (explicit consent + processing record).
- **UI**: `/onboarding` full-page gate forces selection before `/office`
  loads; `VoiceModeChangeModal` inside `/office` for later changes;
  `user_direct` requires an extra acknowledgement checkbox citing SB-1001
  and CASL. `useVoiceMode()` hook wraps both endpoints.
- **Events**: `voice_mode.selected` and `voice_mode.changed` land in
  `task_events` with `event_category = "onboarding"` and the ledger row
  ID in payload.
- **Env vars**: `EMAIL_FROM_SELVA` (default `noreply@selva.town`) controls
  the co-branded address for dyad mode. `NEXUS_API_URL` (workers → API
  lookup for voice-mode gate) and `WORKER_API_TOKEN` (existing) are reused.

## Autonomous Pipeline Security (v2.1.1)

- **Dispatch Dedup**: `HeartbeatService` tracks recently dispatched `lead_id`
  values in a `Map<string, number>` with 24h TTL. Same lead cannot be
  dispatched twice within 24 hours.
- **Dispatch Cap**: `MAX_DISPATCHES_PER_TICK = 10`. Prevents cost explosion
  when CRM has many hot leads. Logs warning when cap is hit.
- **Payload Sanitisation**: Auto-dispatch uses explicit field pick (lead_id,
  contact_id, score, stage, activity_id) instead of `...event.payload` spread.
  Closes playbook injection vector.
- **HITL Re-enabled**: Auto-dispatched CRM tasks now set
  `require_approval: true` (was `false`). Financial cap set to $50/day
  (`financial_cap_cents: 5000`, was `0`).
- **PII Scrubbed**: Task descriptions use `lead:<id>` not contact names.
  Email addresses masked in logs (`aaa***@domain.com`).
- **Tick Concurrency Guard**: `_tickRunning` flag prevents overlapping ticks.
- **CRM Fetch Timeout**: 10s `AbortController` on all PhyndCRM HTTP calls.
- **Single CRM Scrape**: `scrapeTickets()` removed — ticket events extracted
  from the single `scrapeCRM()` call.
- **Email Validation**: RFC-compliant regex (`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
  in `SendEmailTool`, `SendMarketingEmailTool`, and CRM graph `send()`.
- **LLM Placeholder Abort**: CRM graph aborts email send when LLM returns
  `"[LLM unavailable"` placeholder (e.g. due to $0 provider credits).
- **HTML Sanitisation**: `_sanitize_email_html()` strips script, iframe,
  object, embed, form, style tags, `on*` event handlers, and
  `javascript:`/`data:` URLs from email body before template injection.
- **CAN-SPAM Compliance**: Physical address ("Innovaciones MADFAM SAS de CV ·
  Mexico") added to email footer. `List-Unsubscribe` header added to all
  marketing email Resend API payloads.
- **Sender Lockdown**: `from_address` parameter removed from `SendEmailTool`.
  All emails use `EMAIL_FROM` env var — no agent-controlled sender forgery.
- **Events Auth**: `POST /api/v1/events` now requires `Bearer` auth (was
  unauthenticated). Workers already send `WORKER_API_TOKEN` in all event
  emission calls.
- **Proxy Error Sanitisation**: Inference proxy returns generic error messages
  ("Inference service unavailable") instead of `str(exc)` which could leak
  provider API keys, URLs, or internal configuration.
- **Proxy Limits**: `max_tokens` capped at 32768. Embedding input capped at
  256 items per request.

## Production Hardening (v0.3.0)

- **Worker Concurrency**: `MAX_CONCURRENT_TASKS` env var (default 3). Semaphore-bounded
  `asyncio.create_task()` with graceful shutdown drain.
- **LLM JSON Retry**: `implement()` retries LLM up to 2 times on `JSONDecodeError`,
  re-prompting with error context. Returns `status: "error"` on exhaustion (not
  placeholder). Conditional edge `implement → END` when `status == "error"`.
- **Git Credential Isolation**: `BashTool.execute()` accepts `env` kwarg. Token passed
  to `create_pr()` via subprocess env instead of `os.environ`.
- **Worktree Cleanup**: `_cleanup_stale_worktrees()` runs on startup, removes
  worktrees older than `WORKTREE_STALE_HOURS` (default 24).
- **Dispatch Rate Limiting**: Per-user sliding window via `MessageRateLimiter` on
  `POST /dispatch` (default 10 req/60s). Config: `DISPATCH_RATE_LIMIT`,
  `DISPATCH_RATE_WINDOW`.
- **BashTool Sandbox**: Blocks `cd ..` when `allowed_cwd` is set.
- **Approval Polling Jitter**: `poll_interval * (0.5 + random())` to avoid
  thundering herd.
- **DLQ Monitoring**: `GET /api/v1/health/dlq-stats` returns depth and recent entries.
- **Stale Task Reaper**: `POST /api/v1/swarms/tasks/reap-stale` auto-fails
  queued/pending tasks older than 1 hour.
- **Inference Retry + Fallback**: `ModelRouter.complete()` retries primary once (1s
  delay), then falls through to alternative providers.
- **Approval Audit Trail**: `responded_by` column on `approval_requests` (migration
  0012). Populated from JWT `sub` claim.
- **Git Identity**: `GitTool.configure_identity()` sets repo-local `user.name` /
  `user.email` before every agent commit. Config: `GIT_AUTHOR_NAME` (default
  `selva-bot`), `GIT_AUTHOR_EMAIL` (default `bot@selva.town`).
- **Worker-to-API Auth**: Centralized via `auth.py:get_worker_auth_headers()`.
  Reads `WORKER_API_TOKEN` env var (default `dev-bypass`). Used by
  `task_status.py`, `event_emitter.py`, `interrupt_handler.py`, and
  `__main__.py:_fetch_agent_skills()`. No hardcoded tokens in source.
- **CSRF Exemptions**: `/api/v1/events`, `/api/v1/approvals`, `/api/v1/billing/`,
  `/api/v1/swarms/tasks/` added to CSRF exempt prefixes (worker-to-API calls).
- **PR Creation Compat**: `GitTool.create_pr()` resolves `OWNER/REPO` from git
  remote URL and uses `--repo` flag instead of `-C` (compat with older `gh` CLI).
- **Worktree Branch Naming**: `plan()` creates worktree with branch
  `selva/task-{id}` (was `task-{id}`) to match `push_gate()` expectations.

## Enterprise Mexican Market (v2.0.0)

- **Sprints 1-7**: KarafielAdapter (compliance), DhanamAdapter (billing+
  economic data), TezcaAdapter (legal), CrawlerAdapter (scraping).
  74 tools, 12 graphs (billing, accounting, sales, intelligence),
  15 es-MX locale skills, TenantConfig with RFC validation, multi-tenant
  provisioning with 6 Mexican departments, daily task limits.
  See ROADMAP.md for detailed sprint breakdown.

## Final Remediation (v1.2.1)

- **Hub client test fix**: `test_hub_client.py` used `AsyncMock` for
  httpx response objects, but httpx `Response.json()` and
  `raise_for_status()` are synchronous. Fixed to use `MagicMock` for
  responses, `AsyncMock` only for the `get()` method. 2/2 tests now pass.
- **selvatown.com redirect**: `infra/cloudflare/redirect-rules.yaml` —
  301 permanent redirect from `selvatown.com` (and `*.selvatown.com`)
  to `selva.town` preserving path and query string.

## Solarpunk Visual Overhaul Phase 3-4 (v1.2.0)

- **Solarpunk Companions**: 5 companion sprites redrawn — cat with flower
  collar, dog with leaf bandana, bio-robot with moss patches, plant dragon
  with leaf wings, tropical parrot with solar feathers.
- **Solarpunk Emotes**: 9 emotes redrawn — leaf wave, sun thumbsup, flower
  heart, sunshine laugh, sprout think, leaf clap, solar fire, bioluminescent
  sparkle, herbal tea cup.
- **Animated Tiles**: 3 animated tile types (water shimmer, candle flame,
  grow-light pulse) with 4-frame cycles at 200ms intervals. Tile animation
  engine in OfficeScene with timer-based frame cycling.
- **Agent Idle Animations**: 3 idle sub-states (breathing, look-around,
  stretch) cycling every 5s. Working head-bob, waiting-approval sway,
  error alpha reduction + red tint. Companion vertical bob when stationary.

## Solarpunk Visual Overhaul Phase 2 (v1.1.0)

- **Living Office Map**: Complete map generator rewrite. 4 department
  biomes (Tech Greenhouse, Library Garden, Market Garden, Zen Garden)
  radiating from a central atrium garden. Glass corridors with vertical
  water channel divide. Blueprint gazebo. 4 review stations, 2 dispatch
  stations, 3 spawn points. 9 TMJ layers, zero empty floor tiles.
- **Atmospheric Lighting**: Department ambient tints via ADD-blended
  overlays (purple grow-light, teal library, golden cafe, zen green).
  5 skylight golden light pools with pulsing alpha + solar sparkle
  particles. Zone-specific: purple spore drift (engineering), cool blue
  water ripples (support), rising bioluminescent spores (atrium).
- **Solarpunk Agent Halos**: idle=moss green, working=solar gold,
  paused=wood tone, error=deep red.

## Solarpunk Visual Overhaul Phase 1 (v1.0.0)

- **Solarpunk Palette**: Environment tokens overhauled to warm earth tones
  (wood #8b7355, bamboo #c8b896, moss #4a9e6e). New "solarpunk" preset
  with tech-garden, market-garden, zen-garden, library-garden department
  biomes. Review station bright solar gold (#f6d55c) for contrast.
- **4-Direction Walk Cycles**: 12-pose avatar system (4 dirs × 3 frames).
  `AvatarCompositor` generates 384x32 spritesheets. FF6-style JRPG
  1-2-1-3 walk pattern at 8fps. Directional hair variants for all 8 styles.
  `createAvatarAnimations()` exported for per-texture animation registration.
- **Solarpunk UI Tokens**: 17 Tailwind colors (wood, bamboo, moss, leaf,
  solar, sky, earth, glass, bloom, glow, sand). CSS classes: solarpunk-panel,
  solarpunk-btn, solarpunk-border, leaf-overlay. Theme color → #2a2218.
- **Particle Overhaul**: 6 new particle textures (leaf 6x4, petal 4x4,
  firefly 3x3, spore 3x3, sparkle 3x3, glint 2x2). Ambient dust replaced
  with floating leaves + fireflies. Agent status: gold glint (working),
  leaf burst (spawn). Green/gold spawn-in effect.

## Competitive Dominance Wave 4 (v0.9.0)

- **Mobile UX Polish**: Haptic feedback (`navigator.vibrate(50)`) on
  touch action buttons. Compact layout for screens <640px. `MobileNav`
  bottom tab bar (Office/Chat/Tasks/Settings) visible only on touch
  devices. CSS safe area padding for notched phones.
- **Competitive Benchmark**: `docs/BENCHMARK.md` — living document with
  feature matrices vs Hermes Agent, OpenClaw, Gather, WorkAdventure,
  CrewAI, LangGraph, MS Agent Framework. Platform stats, security posture,
  parity scorecard.

## Competitive Dominance Wave 3 (v0.8.0)

- **Tool Expansion (40→54)**: 14 new tools across 5 categories:
  Email (SendEmail via Resend, ReadEmail), Calendar (Create/List via
  Google adapter), Database (SQLQuery read-only, SQLWrite with approval,
  DatabaseSchema), HTTP (HTTPRequest SSRF-protected, GraphQL, Webhook
  with HMAC), Documents (GeneratePDF, ParsePDF, MarkdownToHTML,
  GenerateChart). All follow BaseTool ABC with graceful degradation.
- **A2A Protocol**: Agent-to-Agent interop package (`packages/a2a/`).
  `GET /api/v1/a2a/.well-known/agent.json` — AgentCard discovery.
  `POST /api/v1/a2a/tasks/send` — task exchange.
  `POST /api/v1/a2a/tasks/sendSubscribe` — SSE streaming.
  `A2AClient` for calling external agents. `CallExternalAgentTool`
  registered in tool registry. CSRF-exempt (Bearer auth).

## Competitive Dominance Wave 2 (v0.7.0)

- **Voice Mode (STT)**: `SpeechToTextTool` in `builtins/stt.py` — OpenAI
  Whisper API integration (multipart POST, auto content-type detection).
  Voice API: `POST /api/v1/voice/transcribe` (audio upload → text),
  `POST /api/v1/voice/dispatch` (text → SwarmTask). Meeting graph
  `transcribe()` node tries STT tool first, falls back to LLM.
  Tool count: 40 built-in tools (at v0.7.0).
- **LiveKit SFU Scaling**: Hybrid P2P/SFU proximity video. When player
  count exceeds `LIVEKIT_THRESHOLD` (default 5), server sends `mode: "sfu"`
  in proximity messages and LiveKit credentials on join. Client auto-switches
  from simple-peer to LiveKit Room with proximity-based track subscription.
  `livekit.ts` handler generates `AccessToken` with `VideoGrant`.
  `useProximityVideoLiveKit.ts` hook provides same interface as P2P hook.
  Docker: `livekit/livekit-server` service on ports 7880-7882.
  Config: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.

## Competitive Dominance Wave 1 (v0.6.0)

- **Screen Sharing Polish**: Quality presets (`auto`/`720p`/`1080p`) via
  `getDisplayMedia` video constraints. System audio capture via
  `AudioContext.createMediaStreamDestination()` mixing system + mic tracks.
  Quality dropdown in `MediaControls.tsx` (visible during sharing).
- **Iterative Skill Refinement**: `SkillRefiner._llm_refine()` now loops
  up to `max_iterations=3` — refine via LLM, validate in sandbox, retry
  with error context on failure. `RefinerMetrics` dataclass tracks
  `skills_checked`, `skills_refined`, `skills_failed`, `total_iterations`,
  `avg_refinement_ms`. API: `GET /api/v1/skills/refiner/metrics`.
- **PWA Support**: `manifest.json` ("MADFAM Office", standalone, indigo
  theme), minimal service worker (`sw.js` — cache shell, network-first,
  skip API/WS), `ServiceWorkerRegistrar` client component, PWA icons
  (192x192 + 512x512). Mobile "Add to Home Screen" now works.

## Codebase Stability (v0.5.2)

- **Skills Package Fix**: Resolved dual-path collision — `pyproject.toml`
  `where=["src"]` was hiding the real `selva_skills/` root package.
  Moved `hub.py`, `refiner.py`, `skill_md.py` from `src/` into root
  package. Deleted conflicting `src/selva_skills/registry.py`.
- **Worker Settings**: Added missing `environment: str = "development"`
  field to worker `Settings` class. Validator `_validate_production_safety`
  was crashing with `AttributeError` on every instantiation.
- **Colyseus State Sync**: Moved megaphone and spotlight from module-level
  `let` variables to `OfficeStateSchema` fields (`megaphoneSpeaker`,
  `spotlightPresenter`). Eliminates race conditions across rooms.
  `getMegaphoneSpeaker()`, `handleMegaphoneStop()`, `releaseMegaphone()`
  now accept `state` parameter.
- **Player-Not-Found Errors**: 9 Colyseus handler locations now send
  `client.send("error", { message: "Player not found" })` instead of
  silently returning (megaphone, spotlight, avatar, teleport, movement,
  status x3, emotes).
- **Admin SSO Logger**: Replaced 7 `console.error/warn` calls in
  `apps/admin/src/app/api/auth/callback/route.ts` with dev-only logger.
- **Dashboard Accessibility**: Added `aria-live="polite"` to
  MetricsDashboard stats container and DashboardPanel kanban area.
- **Hook Error Naming**: Standardized `catch (e)` → `catch (err)` across
  18 occurrences in useMapEditor, useWorkflowTemplates, useMarketplace,
  useWorkflow.
- **Makefile Dev Cleanup**: `make dev` now uses `trap "kill 0"` for
  graceful process cleanup on Ctrl+C.

## Codebase Remediation (v0.5.1)

- **K8s workers.yaml**: Fixed duplicate `env:` key in production deployment
  that silently dropped `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, and 3
  other env vars. Merged into single `env:` block with all 8 variables.
- **Alembic Migration Chain**: Orphaned `0004_wave2_tables.py` renamed to
  `0014_wave2_tables.py`, chained after migration 0013. Removed duplicate
  `approval_requests` table creation (already in migration 0000). Adds
  `session_checkpoints` table used by `checkpoints.py`.
- **`run_async` Consolidation**: 8 duplicate `_run_async()` implementations
  across graph files consolidated into single `run_async()` export in
  `graphs/base.py`. All 7 consuming graphs import as `_run_async`.
- **ACP QA Oracle Sandbox**: Replaced hardcoded `tests_passed = True` with
  actual `BashTool` sandbox execution (late import with graceful fallback).
  Tests are now run via subprocess with 60s timeout.
- **Gateway SSRF Protection**: `_validate_webhook_url()` helper in
  `routers/gateway.py` blocks private IP ranges (127/8, 10/8, 172.16/12,
  192.168/16, 169.254/16, ::1/128, fc00::/7), enforces http/https scheme,
  2048-char limit. Applied to all 17 webhook handlers.
- **Bare Exception Logging**: 16 silent `except Exception: pass` blocks
  across nexus-api routers and worker graphs now log with `exc_info=True`.
  Fire-and-forget ops use `logger.debug`, correctness-affecting use `warning`.
- **Settings Consolidation**: `analytics.py` and `gateway.py` now use
  centralized pydantic `Settings` instead of direct `os.environ.get()`.
  Added `posthog_api_key`, `posthog_host`, `selva_webhook_secret` to
  nexus-api config.
- **Frontend URL Config**: Landing page `APP_URL` reads
  `NEXT_PUBLIC_APP_URL` env var with production fallback.
- **CI Python Type Checking**: Added `typecheck-py` job to CI pipeline
  running `uv run mypy` on all Python packages. Required before build.
- **Docker Dev Parity**: Dev compose now uses `pgvector/pgvector:pg16`
  (was `postgres:16-alpine`) for production parity. Added coturn service
  for WebRTC TURN in development.
- **Frontend Constants**: Game magic numbers consolidated into
  `apps/office-ui/src/game/constants.ts` (18 constants). Hook-level
  constants and event bus keys in `apps/office-ui/src/lib/constants.ts`.
- **Dev Logger**: `apps/office-ui/src/lib/logger.ts` — production-silent
  console wrapper. Replaces raw `console.warn/error` in 5 files.
- **Accessibility**: `aria-label` on video elements in `VideoOverlay.tsx`.
- **Shared Types**: `companionType` tightened from `string` to
  `'' | 'cat' | 'dog' | 'robot' | 'dragon' | 'parrot'` in
  `packages/shared-types/src/office.ts`.
- **Thread-Safety Docs**: Module-level mutable state in `auth.py` (JWKS
  cache) and `http_retry.py` (circuit breaker) documented with
  concurrency assumptions.
- **Smoke Test**: Port numbers now configurable via env vars
  (`NEXUS_API_PORT`, `OFFICE_UI_PORT`, `COLYSEUS_PORT`, `WORKER_PORT`).
- **Redis Slot Docs**: Inline comments in `docker-compose.yml` documenting
  DB 0 (nexus-api) and DB 1 (colyseus) slot assignments.

## Landing Page + Demo Mode (v0.5.0)

- **Landing page** (`/`): Server-rendered marketing page. No auth, no game deps.
  Sections: Hero, Feature Grid, How It Works, Footer. Uses existing design tokens.
- **Demo mode** (`/demo`): Sandboxed office with 8 simulated agents. Client
  generates unsigned JWT with `org_id: "demo-public"`, `roles: ["demo"]`.
  Colyseus `verifyToken()` recognizes demo tokens before JWKS verification.
  `filterBy(["orgId"])` isolates demo rooms from real rooms.
- **DemoSimulator** (`apps/colyseus/src/demo/DemoSimulator.ts`): Populates 8
  hardcoded agents, cycles them through idle → working → waiting_approval → idle
  every 12-15s. Auto-approves after 15s if no human action.
  `resolveApproval()` handles human approve/deny locally.
- **OfficeExperience** (`components/OfficeExperience.tsx`): Extracted from old
  `page.tsx`. Accepts `mode: 'live' | 'demo'`. Demo mode hides calendar,
  marketplace, map editor, workflow editor, ops feed, metrics.
- **Hook bypasses**: `useApprovals`, `useTaskDispatch`, `useCalendar`,
  `useMeetingNotes`, `useTaskBoard`, `useEventStream` all check `isDemo()`
  and skip WebSocket connections / API polling in demo mode.
- **Route changes**: `/` → landing, `/office` → protected office (was `/`),
  `/demo` → public demo. Login default redirect changed from `/` to `/office`.
- **Config**: `NEXT_PUBLIC_DEMO_ENABLED` env var (default true) controls
  visibility of "Try Demo" CTA on landing page.

## Agent Learning Loop (v0.4.0)

- **Experience Recording**: `learning.py:record_experience()` stores task outcomes
  in `ExperienceStore` (per-role, 30-day temporal decay) and `MemoryStore`
  (per-agent). Score mapping: completed=1.0, denied=0.2, failed=0.0. Fire-and-forget.
- **Reflexion**: `learning.py:generate_reflexion()` calls LLM for self-critique on
  failures (Reflexion NeurIPS 2023 pattern). Falls back to basic text when LLM
  unavailable. Stored with score=0.3 and `metadata.type="reflection"`.
- **Experience Injection**: `prompts.py:build_experience_context()` retrieves
  similar past experiences and agent memories, injecting them into plan/implement/
  review prompts. Graceful degradation to empty string on any error.
- **Agent Performance Tracking**: 6 columns on `Agent` model (`tasks_completed`,
  `tasks_failed`, `approval_success_count`, `approval_denial_count`,
  `avg_task_duration_seconds`, `last_task_at`). `PATCH /api/v1/agents/{id}/stats`
  accepts delta increments with running average for duration. Migration `0013`.
- **Bandit Reward**: `learning.py:update_bandit_reward()` updates `ThompsonBandit`
  after every task (not just puppeteer). Reward: 1.0 (success), 0.2 (partial), 0.0
  (failure). Persisted to `BANDIT_PERSIST_PATH`.
- **Performance-Aware Dispatch**: Skill-based agent matching in `swarms.py` weighted
  by `_compute_perf_weight()` (30% performance, 70% skill overlap). New agents
  default to 0.5 (neutral). `perf_weight = 0.5 * approval_rate + 0.5 * completion_rate`.
- **Config**: `MEMORY_PERSIST_DIR` (default `/tmp/selva-memory`),
  `BANDIT_PERSIST_PATH` (default `/tmp/selva-bandit.json`).
- **CSRF**: `/api/v1/agents/` stats endpoint uses Bearer auth which bypasses CSRF.

## Autonomous Dev Readiness (v0.3.1)

- **test() Node Fix**: `test()` uses `_run_async()` instead of
  `asyncio.get_event_loop()`, which crashed in ThreadPoolExecutor threads.
  `run_async()` is now a shared export from `graphs/base.py`, imported as
  `_run_async` in all 7 graph files (coding, crm, deployment, meeting,
  project, puppeteer, research). No duplicate implementations remain.
- **Worker Auth Hardening**: `WORKER_API_TOKEN` env var (default `dev-bypass`).
  `auth.py:get_worker_auth_headers()` centralizes all worker-to-API auth.
  No hardcoded `"Bearer dev-bypass"` in source files.
- **Org Config Bootstrap**: `make setup-org-config` copies
  `data/org-config-template.yaml` to `~/.selva/org-config.yaml`. Wired
  into `make dev-full`. Worker logs warning when org config missing.
- **Enhanced System Prompts**: `prompts.py` provides `build_plan_prompt()`,
  `build_implement_prompt()`, `build_review_prompt()` with repo context
  (top-level listing, README excerpt, CLAUDE.md conventions, language
  detection). Strict JSON format instructions prevent LLM returning
  markdown instead of file objects.
- **Docker Compose Compat**: `DOCKER_COMPOSE` Makefile variable auto-detects
  `docker-compose` (v1) vs `docker compose` (v2 plugin).

## Port Assignments

> See [docs/PORTS.md](docs/PORTS.md) for canonical port assignments.

| Port | Service | Notes |
|------|---------|-------|
| 4300 | nexus-api | Central API |
| 4301 | office-ui | Next.js frontend |
| 4302 | admin | Admin dashboard |
| 4303 | colyseus | Game state server |
| 4304 | gateway | Heartbeat daemon (health + metrics HTTP) |
| 4305 | workers | Worker health + metrics HTTP server |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Commands

```bash
make dev              # Start all services (TS + Python + Worker)
make dev-full         # Full boot: Docker + migrations + all services
make dev-seed         # Seed departments and agents (requires nexus-api running)
make worker           # Run worker process independently
make test             # Run all tests
make lint             # Run all linters
make typecheck        # TypeScript + mypy
make build            # Build all packages
make docker-dev       # Start Postgres + Redis
make db-migrate       # Run Alembic migrations
make db-seed          # Seed default departments and agents (13 generic)
python scripts/seed-madfam-org.py  # Seed MADFAM org: 4 nodes, 10 named agents
make smoke-test       # Verify all services are healthy
make generate-assets  # Regenerate pixel-art sprite PNGs
make generate-variants # Generate palette-themed sprite/tile variants
make generate-map     # Procedurally generate office map (WFC)
make generate-office-map  # Generate hand-crafted 50x28 office map
make post-process     # Optional ImageMagick upscale/WebP conversion
make db-backup        # Backup PostgreSQL database
make db-restore       # Restore from backup (BACKUP_FILE=<path>)
make db-verify-backup # Verify backup integrity (BACKUP_FILE=<path>)
make worktree-cleanup # Remove stale git worktrees (STALE_HOURS=24)
make setup-org-config # Bootstrap ~/.selva/org-config.yaml from template

pnpm dev              # TypeScript services only
pnpm build            # Build TypeScript packages
pnpm lint             # ESLint
pnpm test             # TypeScript tests (660+ tests across 55+ suites)
pnpm typecheck        # TypeScript type checking

uv run pytest packages/ apps/nexus-api/  # Python tests (670+ tests)
uv run pytest apps/workers/tests/       # Worker tests (140+ tests)
uv run ruff check .   # Python linting
uv run mypy .         # Python type checking
```

## Tool + Skill Audience Split (admin vs tenant)

Selva enforces a two-tier audience model so the MADFAM platform swarm
and tenant (customer-org) swarms see different registries:

- `Audience.PLATFORM` — MADFAM-only tools/skills: Cloudflare, K8s,
  ArgoCD, Kustomize, Enclii, GitHub org admin, Vault, Janua admin,
  tenant_identities CRUD, Stripe Connect (platform creates tenant
  accounts), Resend domain, Karafiel org/SAT upload/PAC register,
  Dhanam space/subscription create, PhyndCRM tenant bootstrap, and
  the five MADFAM runbook skills (cluster-triage, dns-migration,
  incident-triage, staging-refresh, tenant-onboarding) plus meta
  skills (skill-creator, mcp-builder).
- `Audience.TENANT` (default) — everything a tenant swarm can use:
  email send, CRM primitives, their own calendar/SMS/voice/Discord/
  Telegram, Karafiel CFDI generate/stamp, Dhanam credit-ledger query,
  PhyndCRM tenant-config read, pricing/ops/legal/marketing tools, etc.

**How it flows end-to-end**:

1. `PLATFORM_ORG_ID` env defines the MADFAM internal org_id. Unset =
   everyone is tenant audience (safe default).
2. Worker resolves audience from the task's `org_id` at dispatch time
   (`selva_permissions.resolve_audience`), binds it via
   `selva_tools.with_audience(...)` context manager.
3. `BaseTool.__init_subclass__` auto-wraps every tool's `execute()`
   with `enforce_audience(self.audience, tool_name=self.name)`. A
   tenant swarm invoking a platform tool raises `AudienceMismatch`
   before the tool body runs.
4. `ToolRegistry.get_specs(audience=...)` filters platform tools from
   the spec list when tenant audience is requested (defense in depth
   for any future caller that binds tools to an LLM).
5. Skill loader (`SkillRegistry.activate(name, audience=...)`) raises
   `SkillAudienceMismatch` if a tenant swarm asks for a platform skill.
6. Nexus-api `POST /api/v1/swarms/dispatch` returns `403
   audience_mismatch` when a tenant caller names a platform skill in
   `required_skills`.

**Feature flag + shadow mode**:

- `AUDIENCE_FILTER_ENABLED` env var (default off in code). When off, every
  enforcement point logs a `audience_shadow_block` warning instead
  of raising/returning 403. Lets ops observe the production rate of
  would-be-blocks for 24-48h before flipping to enforce.
- Production (`infra/k8s/production/configmap.yaml`) sets
  `AUDIENCE_FILTER_ENABLED=true` — enforcement is live. New environments
  should follow [docs/AUDIENCE_FILTER_ROLLOUT.md](docs/AUDIENCE_FILTER_ROLLOUT.md).
- When ready in a new env, set `AUDIENCE_FILTER_ENABLED=true` on workers +
  nexus-api. The three gates (tool execute, skill activate, dispatch
  endpoint) all flip in the same release.

**Regression test**: `packages/tools/tests/test_platform_tool_registry.py`
hardcodes the list of ~130 platform tools and fails CI if any of them
gets accidentally promoted to TENANT (or renamed without updating the
list). New platform tools MUST be added to the list + tagged via the
module-bottom `for _cls in (…): _cls.audience = Audience.PLATFORM`
block pattern (see any existing platform module for template).

## MADFAM Ecosystem

- **Janua** handles all authentication. Never implement custom auth. Use the
  `get_current_user` dependency in FastAPI and the Next.js middleware for session
  validation. Janua tokens are JWTs with `sub`, `email`, `roles`, and `org_id` claims.
  - **Enterprise SSO Mapping**: To support multi-tenant boundaries (RLS in PostgreSQL), Janua must be configured with an OpenID Connect Enterprise Connection. Navigate to the Janua dashboard and map your IdP's group/tenant ID claim to the `org_id` token claim. This `org_id` is automatically extracted by the `TenantRLSMiddleware` in `security.py` to enforce secure PostgreSQL Row-Level Security isolation boundaries.

- **Dhanam** handles billing and subscriptions. Compute token budgets are enforced
  by the orchestrator package and tracked in the `compute_token_ledger` table.
  Use the billing router at `apps/nexus-api/src/routers/billing.py`.

- **Enclii** handles deployment. `enclii.yaml` (repo root) defines all six
  services (nexus-api, office-ui, admin, colyseus, gateway, workers).
  The `.github/workflows/deploy.yml` pipeline builds images and notifies Enclii.

- Read sibling repo `llms-full.txt` files for full API surfaces of Janua, Dhanam,
  and Enclii.

## Coding Standards

### Python
- **Linter**: ruff (target py312, line-length 100)
- **Type checker**: mypy (strict mode)
- **Models**: pydantic for all request/response schemas
- **ORM**: SQLAlchemy with async sessions
- **Tests**: pytest with pytest-asyncio
- **Imports**: isort via ruff, `selva` as known-first-party

### TypeScript
- **Strict mode**: enabled in all tsconfig.json files
- **Linter**: ESLint with shared config from `packages/config/eslint`
- **Formatter**: Prettier
- **Tests**: vitest with jsdom + @testing-library/react for UI components
- **Build**: Turborepo for monorepo orchestration
- **Package manager**: pnpm with workspace protocol

## Git Workflow

- Feature branches only -- never commit directly to `main`.
- Conventional commits, checked by commitlint from the husky `commit-msg` hook
  that `pnpm install` installs. Allowed types:
  `build`, `chore`, `ci`, `deploy`, `docs`, `feat`, `fix`, `perf`, `refactor`,
  `revert`, `rollback`, `style`, `test`
  (`deploy`/`rollback` belong to the release workflows -- do not use them by hand).
  Scopes are free-form. Header limit is 100 characters.
  Emergency bypass: `HUSKY=0 git commit ...`.
- PRs require CI to pass before merge.

## Skills System

The `packages/skills/` package implements the AgentSkills standard.

- **Core skills** (25) live in `packages/skills/skill-definitions/`. Always loaded.
- **Community skills** (~25) live in `packages/skills/community-skills/`. Vendored from
  [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills).
  Disabled by default.
- `SkillTier` enum: `CORE` | `COMMUNITY`. Set by the registry during discovery, not
  from YAML frontmatter.
- Enable community skills via:
  - Env var: `SELVA_COMMUNITY_SKILLS_ENABLED=true`
  - Runtime: `get_skill_registry().enable_community_skills()`
  - REST API: `POST /api/v1/skills/community/enable`
- Core skills always take precedence on name collision with community skills.
- Community skill scripts under `community-skills/` are excluded from ruff linting
  via `extend-exclude` in `pyproject.toml`.

## Dynamic Workflow System (ChatDev 2.0 Parity)

### Workflow Engine (`packages/workflows`)
- **Schema** (`schema.py`): Pydantic models for `WorkflowDefinition`, `NodeDefinition`
  (8 node types: `agent`, `human`, `passthrough`, `subgraph`, `python_runner`,
  `literal`, `loop_counter`, `batch`), `EdgeDefinition` with conditional routing.
- **Compiler** (`compiler.py`): `WorkflowCompiler.compile(workflow_def)` → LangGraph
  `StateGraph`. Supports conditional edges (regex, keyword, expression), context
  window policies (keep_all, keep_last_n, clear_all, sliding_window), and subgraph
  nesting via recursive compilation.
- **Serializer** (`serializer.py`): YAML ↔ WorkflowDefinition roundtrip.
- **Validator** (`validator.py`): Cycle detection (loop counter nodes exempt),
  orphan node warnings, edge reference checks, type-specific config validation.
- Custom workflows dispatched via `graph_type: "custom"` + `workflow_id` in
  `POST /api/v1/swarms/dispatch`. YAML loaded from `workflows` table, compiled
  at runtime by the worker.

### Tool Registry (`packages/tools`)
- **BaseTool** ABC with `name`, `description`, `parameters_schema()`, `async execute()`.
- `ToolRegistry` singleton: 23 built-in tools across 8 categories (file ops, code
  exec, git, web, data, communication, environment, artifacts) at the time this
  section was written. `get_specs(tool_names)` returns OpenAI function-calling
  format.
- **MCP Client** (`mcp/client.py`): `McpToolAdapter` wraps remote MCP tools as
  BaseTool instances. Stdio and HTTP transports. `discover_mcp_tools(transport)`
  auto-registers.

#### SWE pipeline tools (pre-pr-audit building blocks)

These tools are the building blocks the `pre-pr-audit` skill composes into
a pre-submission gate. They're TENANT-audience (default) — any tenant swarm
can use them without platform privileges.

- `git_create_pr` (in `builtins/git.py`) — wraps `gh pr create` with
  pre-flight guards: refuses protected branches (main/master/develop/trunk),
  warns on non-conventional-commit titles, loads `.github/pull_request_template.md`
  when body is empty, auto-adds CODEOWNERS-derived reviewers. Returns the
  PR URL in `data.url`.
- `lint_and_typecheck` (in `builtins/dev_quality.py`) — runs ruff + mypy
  (Python) and/or eslint + tsc (TypeScript). Auto-detects language from
  config-file presence. Missing toolchains are reported as `skipped`, not
  errors. Returns structured `{findings: [...], skipped: [...], summary}`.
- `test_coverage_for_diff` (in `builtins/dev_quality.py`) — runs
  `pytest --cov=. --cov-report=json` (or reuses an existing
  `.coverage.json`), intersects covered lines with lines added or modified
  in `git diff <base_ref>...HEAD`, returns uncovered changed lines per file.
  Skips gracefully when neither pytest nor a pre-rendered coverage file is
  available.
- `deploy_preflight` (in `builtins/deploy_preflight.py`) — runs
  `kustomize build` locally and inspects the rendered YAML. Blocker
  checks: image digest-pinned (rejects `:latest` or mutable tags),
  `resources.requests` present, `securityContext.privileged: false`
  explicit. Advisory (opt-in via `checks=["all"]`): `resources.limits`
  and `imagePullSecrets` for GHCR. Never touches the cluster.

See `packages/skills/skill-definitions/pre-pr-audit/SKILL.md` for how the
skill composes these four tools into a pre-submission gate.

### Agent Memory (`packages/memory`)
- **MemoryStore**: Per-agent FAISS `IndexFlatIP` with metadata. `store()`, `search()`,
  `list_entries()`, `delete()`. Persists to disk (index.faiss + entries.json).
- **EmbeddingProvider**: OpenAI (`text-embedding-3-small`), Ollama
  (`nomic-embed-text`), or hash-based fallback for dev.
- **ExperienceStore** (IER): Per-role task pattern learning with temporal decay
  (30-day half-life). `record()`, `search_similar()`, `get_shortcuts()`.
- **MemoryManager**: Lazy-loading per-agent stores, `get_relevant_context()` for
  LLM prompt injection.

### Workflow CRUD API
- `POST/GET/PUT/DELETE /api/v1/workflows` + `/validate`, `/import`, `/export`
- Alembic migration `0005` adds `workflows` table + `workflow_id` FK on `swarm_tasks`

### Visual Workflow Builder (Phase 4)
- **Blueprint Room**: `dept-blueprint` department zone (maxAgents: 0) at (800,260).
  `blueprint` interactable type emits `open_blueprint` event → opens WorkflowEditor.
- **WorkflowEditor** (`apps/office-ui/src/components/workflow-editor/`): Full-screen
  modal with React Flow canvas, 8 custom node types (Agent, Human, Passthrough,
  Subgraph, PythonRunner, Literal, LoopCounter, Batch), conditional edges, NodePalette
  (drag-and-drop), PropertiesPanel (dynamic form fields), EditorToolbar (New, Save,
  Load, Export YAML, Import YAML, Validate, Run).
- **workflow-converter** (`apps/office-ui/src/lib/workflow-converter.ts`): Bidirectional
  YAML ↔ React Flow conversion. Preserves node positions in `position_x`/`position_y`.
- **useWorkflow hook**: State machine (idle|loading|saving|validating|error) for
  workflow CRUD operations via `/api/v1/workflows` API.
- **Execution monitoring**: `AgentSchema.currentNodeId` (Colyseus) synced via Redis
  pub/sub from worker `_publish_agent_status(current_node_id=...)`. Active nodes
  highlighted in editor canvas. `[nodeId]` label rendered under agent sprites in
  OfficeScene. `ExecutionLog` panel shows chronological events.
- **Custom workflow dispatch**: `graph_type: 'custom'` + `workflow_id` in
  `POST /api/v1/swarms/dispatch`. Worker uses `compiled.astream()` for node-level
  progress streaming via `_run_custom_with_streaming()`.
- **Shared types**: `packages/shared-types/src/workflow.ts` mirrors Python schema.
  `Agent.currentNodeId` optional field.
- **Dependencies**: `@xyflow/react`, `js-yaml` (office-ui).

### Phase 5: Advanced Features

#### Artifact Management (5.1)
- **Storage**: `packages/tools/src/selva_tools/storage/` — `ArtifactStorage` ABC +
  `LocalFSStorage` (content-addressable SHA-256 dedup, layout `<hash[:2]>/<hash[2:4]>/<hash>`).
  `ARTIFACT_STORAGE_PATH` env var or `/tmp/selva-artifacts` default.
- **Tools**: `SaveArtifactTool`, `RetrieveArtifactTool`, `ListArtifactsTool` in
  `builtins/artifact.py`. Registered in `get_builtin_tools()`.
- **REST API**: `apps/nexus-api/nexus_api/routers/artifacts.py` —
  `GET /api/v1/artifacts`, `GET .../download`, `DELETE ...`. Org-scoped.
- **DB**: `Artifact` model in `models.py`, migration `0006_add_artifacts_table`.

#### Batch Processing Node (5.2)
- **Schema**: `NodeType.BATCH` + `BatchAggregateStrategy` enum (`collect`/`merge`/`vote`).
  `NodeDefinition` extended with `batch_split_key`, `batch_aggregate_strategy`,
  `max_parallel`, `delegate_node_id`.
- **Handler**: `BatchNodeHandler` in `nodes/batch.py` — splits `state[split_key]`,
  runs delegate function in parallel via `asyncio.Semaphore`, aggregates per strategy.
- **Compiler**: batch nodes exempt from cycle detection (like loop_counter).
  Delegate functions wired after all nodes are built.
- **Validator**: checks `MISSING_BATCH_SPLIT_KEY`, `MISSING_BATCH_DELEGATE`,
  `INVALID_BATCH_DELEGATE`.
- **UI**: `BatchNode` React Flow component, palette entry, PropertiesPanel fields.

#### Multimodal Inference (5.3)
- **Types**: `ContentType` enum (TEXT/IMAGE_URL/IMAGE_BASE64), `MediaContent` model
  in `packages/inference/madfam_inference/types.py`. `InferenceRequest.messages`
  accepts `list[dict[str, Any]]` for multimodal content blocks. `has_media()` helper.
- **Provider vision**: `InferenceProvider.supports_vision` property (default False).
  OpenAI, Anthropic, Ollama, Generic providers all support vision with
  `_format_messages()` converting to native multimodal formats.
- **Router**: Vision-aware provider selection — filters to `supports_vision=True`
  providers when `request.has_media()`.
- **Open-source providers**: Together AI, Fireworks AI, DeepInfra registered as
  `GenericOpenAIProvider` instances in worker `build_model_router()`. Config fields
  in both worker and nexus-api Settings. `CLOUD_PRIORITY` and `CHEAPEST_PRIORITY`
  updated (deepinfra cheapest, anthropic highest quality).
- **ImageAnalysisTool**: `builtins/image_analysis.py` — constructs multimodal
  messages with image + prompt, returns `requires_inference: True` for worker dispatch.
- **Tool count**: 24 built-in tools (was 23, at v0.5.x).

#### Skill Marketplace (5.4)
- **DB**: `SkillMarketplaceEntry` and `SkillRating` models in `models.py`.
  Migration `0007_add_skill_marketplace` creates both tables with FK CASCADE,
  unique constraint on `(entry_id, user_id)`.
- **REST API**: `routers/marketplace.py` — `GET/POST/DELETE /api/v1/marketplace/skills`,
  `POST .../rate`, `POST .../install`. Search, category filter, sort by
  downloads/rating/newest. Install writes SKILL.md to `community-skills/` and
  calls `registry.refresh()`.
- **Registry**: `SkillRegistry.refresh()` clears caches and re-discovers skills.
  `parse_skill_md_string()` validates YAML from raw strings (marketplace publish).
- **UI**: `SkillMarketplace.tsx` full-screen modal with search, category tabs,
  sort, 2-column card grid, detail view with readme/YAML preview/rating form.
  `useMarketplace` hook (state machine). Accessed via "Skills" button in
  DashboardPanel header.

### Python SDK (`packages/sdk`)
- **Selva** async client: `dispatch()`, `list_agents()`, `get_task()`,
  `wait_for_task()`. Uses `httpx.AsyncClient` with Bearer auth.
- **SelvaSync**: synchronous wrapper using `asyncio.run()`.
- **CLI**: `selva dispatch "desc" --graph-type coding`, `selva agents list`,
  `selva tasks get <id>`, `selva tasks wait <id>`. Click-based.
  Reads `SELVA_API_URL` and `SELVA_TOKEN` env vars.
- **Exceptions**: `SelvaError`, `AuthenticationError`, `TaskTimeoutError`,
  `NotFoundError` with `status_code` attribute.

### Workflow Templates (`data/workflow-templates/`)
- 5 domain YAML templates: `3d-modeling`, `video-production`, `data-analysis`,
  `devops-pipeline`, `content-marketing`. Each includes `loop_counter` nodes
  for cycle-safe review loops.
- **API**: `GET /api/v1/workflows/templates` lists templates,
  `POST /api/v1/workflows/from-template` creates a Workflow from a template.
- **UI**: `TemplateGallery.tsx` full-screen modal with category filter tabs
  (All/Development/Creative/Data/Operations), card grid, and preview.
  Opened via "Templates" button in `EditorToolbar`.

### RL Orchestration / Puppeteer Mode
- **ThompsonBandit** (`packages/orchestrator`): Beta distribution multi-armed
  bandit with `select(candidates)`, `update(agent_id, reward)`, and JSON
  file persistence.
- **PuppeteerOrchestrator**: Extends `SwarmOrchestrator` with bandit-based
  `select_agent()` and `select_agents()` (without replacement).
- **Puppeteer graph** (`apps/workers/graphs/puppeteer.py`):
  `decompose` → `assign` (bandit) → `execute_parallel` (semaphore) →
  `aggregate` → `feedback` → END. Graph type: `"puppeteer"`, timeout: 600s.

### Whiteboards
- **Schema**: `StrokeSchema` (x, y, toX, toY, color, width, tool, senderId) +
  `WhiteboardSchema` (id, strokes ArraySchema). Part of `OfficeStateSchema`.
- **Handler**: `handleWhiteboardDraw` validates and creates strokes; MAX_STROKES=5000
  ring buffer. `handleWhiteboardClear` removes all strokes.
- **UI**: `WhiteboardPanel.tsx` with HTML5 Canvas (800x600), pen/eraser tools,
  8-color palette, 3 width sizes. `useWhiteboard` hook manages state.
- **Interactable**: `whiteboard` is the 10th interactable type in
  `InteractableManager`.

### Spotlight/Presentation
- **Server**: Module-level `currentPresenter` (follows megaphone pattern).
  First-come-first-served. `handleSpotlightStart/Stop`, `releaseSpotlight`
  on disconnect. `spotlightPresenter` field on `OfficeStateSchema`.
- **UI**: `SpotlightView.tsx` (80vh video panel for audience),
  `SpotlightControls.tsx` (start/stop), `useSpotlight` hook.

### In-Browser Map Editor
- **Backend**: `Map` model + migration `0008_add_maps_table`. CRUD API at
  `/api/v1/maps` (follows `workflows.py` pattern). Import/export TMJ.
- **UI**: `MapEditor.tsx` full-screen modal with `MapCanvas` (HTML5 Canvas tile
  painter, 32x32 tiles, pan/zoom, multi-layer), `TilePalette`, `ObjectPalette`,
  `MapToolbar` (New/Save/Load/Export/Import/Undo/Redo/Grid), `MapProperties`.
- **Converter**: `map-converter.ts` — `internalToTmj()`/`tmjToInternal()`
  matching `TiledMapLoader.ts` 9-layer contract.
- **Hook**: `useMapEditor` with undo/redo stack (max 50), CRUD via maps API.
- Accessed via "Map Editor" button in DashboardPanel header.

### Calendar Integration (`packages/calendar`)
- **Adapters**: `GoogleCalendarAdapter` (Calendar API v3),
  `MicrosoftCalendarAdapter` (Graph API v1.0). Both expose `list_events()`
  and `check_busy()` via `httpx.AsyncClient`.
- **DB**: `CalendarConnection` model + migration `0009_add_calendar_connections`.
- **API**: `GET /api/v1/calendar/events`, `POST /connect`, `DELETE /disconnect`,
  `GET /status`.
- **UI**: `CalendarPanel.tsx` sliding panel with event list and join-meeting
  buttons. `useCalendar` hook polls every 60s, auto-sets playerStatus to "busy".

### AI Meeting Notes
- **Graph**: `build_meeting_graph()` — `transcribe` → `summarize` →
  `extract_actions` → `save_artifact` → END. Graph type: `"meeting"`,
  timeout: 300s. Saves results via `LocalFSStorage`.
- **Template**: `meeting-notes.yaml` in `data/workflow-templates/`.
- **UI**: `MeetingNotesPanel.tsx` with summary, action items, transcript.
  `useMeetingNotes` hook dispatches meeting graph and polls for result.
  "Generate Notes" button in `RecordingControls` after recording stops.

### Music/Mood Status
- `TacticianSchema.musicStatus` (`@type("string")`, default `""`). Synced via
  Colyseus. Max 50 chars.
- `handleMusicStatus` in `handlers/status.ts` validates length.
- `MusicStatus.tsx`: text input with 6 mood presets, click-to-edit.
- Rendered below player name labels in `OfficeScene`.

### Chat Persistence
- **DB model**: `ChatMessage` in `models.py` (room_id, sender_session_id,
  sender_name, content, is_system, org_id, created_at). Migration `0010`.
- **REST API**: `apps/nexus-api/nexus_api/routers/chat.py` —
  `GET /api/v1/chat/history?room_id=&limit=&before=` (paginated, org-scoped),
  `POST /api/v1/chat/messages` (fire-and-forget from Colyseus).
- **Colyseus integration**: `handleChat()` and `addSystemMessage()` in
  `handlers/chat.ts` fire-and-forget POST to nexus-api after pushing to
  state schema.
- **Browser notifications**: `useNotifications` hook requests permission,
  shows desktop notifications for chat messages when tab is unfocused.
  Respects DND status. Detects @mentions.

### Teleport & Player List
- **Teleport handler**: `handlers/teleport.ts` — `handleTeleport(state,
  client, { targetSessionId })` moves player to target position + 40px offset.
- **PlayerList component**: sliding panel listing connected players with
  Teleport and Follow buttons per player.

### Admin Controls
- **REST API**: `apps/nexus-api/nexus_api/routers/admin.py` —
  `GET /api/v1/admin/users` (connected users from Redis),
  `POST /api/v1/admin/kick` (publish to Redis channel),
  `POST /api/v1/admin/room-config`. All require `admin` JWT role.
- **AdminPanel component**: user list with kick, MOTD config form.
- **Guest access**: Implemented via Janua `POST /api/v1/auth/guest` endpoint.
  `GuestInvite` model for invite links. `require_non_guest()` FastAPI dependency
  blocks guests from dispatch, approve/deny, workflow/map CRUD, marketplace
  publish/rate/install, calendar connect/disconnect. Colyseus `onAuth` verifies
  JWT via `jose` + JWKS, blocks guests from `approve`, `deny`,
  `megaphone_start`, `spotlight_start`. Frontend `/guest` page, `useUserPermissions`
  hook, `isGuest()` helper in `api.ts`. `TacticianSchema.isGuest` field.

### Meeting Title Badge
- `TacticianSchema.meetingTitle` (`@type("string")`, default `""`). Set by
  calendar integration via `meeting_title` Colyseus message. Max 100 chars.
- `handleMeetingTitle` in `handlers/status.ts`.

### OpenAPI Documentation
- Swagger UI at `/api/v1/docs`, OpenAPI JSON at `/api/v1/openapi.json`.
  Disabled when `ENVIRONMENT=production` (see `docs/PORTS.md`).

### Simplified View
- `SimplifiedView.tsx`: accessible HTML-only alternative to Phaser canvas.
  Department cards (responsive grid), agent list with status badges, approval
  queue with approve/deny buttons, inline chat. Semantic HTML + ARIA landmarks.
- View mode toggle: `viewMode: 'game' | 'simple'` in `page.tsx`, persisted to
  localStorage. Toggle button in HUD.

### MADFAM Intelligence Architecture

- **Org config** (`~/.selva/org-config.yaml`): Secure, per-org configuration
  outside the repo. Defines providers, task-type model assignments, priority
  lists, embedding config, and agent templates. Template at
  `data/org-config-template.yaml`. Loaded by `load_org_config()` (cached via
  `@lru_cache`). API keys referenced by env var name, never plaintext.
- **Task-type routing**: `TaskType` enum (9 values: planning, coding, fast_coding,
  review, research, crm, support, vision, embedding). Graph nodes pass
  `task_type` to `call_llm()` → `RoutingPolicy.task_type` → router checks
  `org_config.model_assignments` → sets `policy.model_override` + selects
  provider. Falls through to default priority-list routing when no assignment
  matches.
- **Model override**: All providers (OpenAI, Anthropic, Ollama) honor
  `request.policy.model_override` in `_build_body()`, falling back to
  `self._model` when not set.
- **New providers**: SiliconFlow (`SILICONFLOW_API_KEY`, GLM-5) and Moonshot
  (`MOONSHOT_API_KEY`, Kimi K2.5) registered via `build_router_from_env()` in
  `packages/inference/madfam_inference/factory.py`. Org config can define
  additional providers dynamically.
- **Inference proxy**: OpenAI-compatible gateway at `/v1/chat/completions` and
  `/v1/embeddings` (`routers/inference_proxy.py`). Ecosystem services (Fortuna,
  Yantra4D, PhyndCRM) point their OpenAI SDK `base_url` here to centralise all
  LLM calls through the `ModelRouter`. Auth: Bearer `WORKER_API_TOKEN`. Optional
  routing headers: `X-Task-Type`, `X-Sensitivity`.
- **Service registry**: `OrgConfig.services` tracks external accounts (Resend,
  Anthropic, DeepInfra, Stripe, etc.) with plan, capacity, and payment status.
  Production config: `infra/k8s/production/org-config.yaml` (ConfigMap mounted
  at `/etc/selva/org-config.yaml`).
- **Agent roster (default)**: 13 agents across 4 departments (Engineering×6, Research×3,
  CRM×2, Support×2) with cross-functional skills. Seed script is idempotent
  (skips existing agents by name).
- **MADFAM Production Roster** (`scripts/seed-madfam-org.py`): 10 named agents across 4 nodes:
  - **Executive Brain Trust**: Oráculo (Strategic Advisor, L10), Centinela (Chief of Staff, L9), Forjador (CTO, L10)
  - **Build & Run Engine**: Telar (Product Owner, L7), Códice (Lead Dev, L9), Vigía (SRE, L8)
  - **Growth & Market Syndicate**: Heraldo (Growth Director, L8), Nexo (CRM Lead, L8)
  - **Physical-Digital Bridge**: Áureo (Finance Controller, L7), Espectro (MES Supervisor, L7)
  - Model assignments: Opus 4 for planning, Sonnet 4 for coding/review/research, Haiku 4.5 for CRM/support
- **New synergy rules**: "Quality Pipeline" (coding+webapp-testing, 1.3×).
  Total: 8 default rules.
- **Fortuna contract**: Fortuna consumes Selva's `/v1/` proxy for all LLM
  calls. It does NOT have direct provider credentials. Selva routes Fortuna's
  requests through the ModelRouter like any other ecosystem service. Fortuna's
  only LLM provider is `openai` (OpenAI-compatible, pointed at Selva proxy).
- **Configurable embeddings**: `EmbeddingProvider` accepts optional
  `provider_name`, `model`, `base_url` for org-config-driven embedding
  providers (e.g. DeepInfra Nemotron). Falls back to OpenAI
  text-embedding-3-small.

## Architecture Notes

- **Worker execution pipeline**: `process_task()` in `__main__.py` drives the
  full task lifecycle: (1) set status to `"running"` via `task_status.py`, (2)
  execute the LangGraph graph, (3) map graph status → API status
  (`pushed`/`completed` → `"completed"`, `blocked`/`denied`/`error` → `"failed"`)
  and PATCH to `nexus-api`, (4) publish agent status to Colyseus via Redis
  pub/sub. Timeouts and exceptions also PATCH `"failed"` with error details.
  All status updates are fire-and-forget (failures logged, never raised).
- **Coding graph execution**: `plan()` creates a git worktree and sets
  `branch_name: "selva/task-{id}"`. `implement()` calls the LLM requesting
  JSON `{"files": [...]}`, parses the response, and writes files to the worktree
  via `_write_files_to_worktree()` (with path traversal security checks). Falls
  back to a placeholder file when no LLM is configured. `push_gate()` calls
  `git_tool.commit()` + `git_tool.push()` before worktree cleanup on approval.
- **Permission engine wiring**: `check_permission()` in `base.py` evaluates an
  `ActionCategory` against the `PermissionEngine`. Called by `implement()`
  (`file_write`), CRM `send()` (`email_send`), and deployment `validate()`
  (`deploy`). Returns `DENY` → node returns `status: "blocked"`. The
  `push_gate` and `deploy_gate` use `interrupt()` for ASK-level gating.
  Skill-based overrides apply when `agent_skill_ids` are present.
- **GitHub credential handling**: `GitTool.configure_credentials()` sets a
  repo-local `credential.helper` echoing the token. `push()` accepts an
  optional `token` kwarg and calls `configure_credentials()` automatically.
  `push_gate()` reads `settings.github_token` and passes it through.
- **PR creation after push**: `_create_pr_after_push()` in `coding.py` calls
  `GitTool.create_pr()` (which invokes `gh pr create`) after a successful push.
  Fire-and-forget — failures are logged, never raised.
- **Deployment graph**: `apps/workers/selva_workers/graphs/deployment.py`
  implements `validate → deploy_gate (interrupt) → deploy → monitor → END`.
  Uses `DeployTool` and `DeployStatusTool` from `packages/tools`.
- **Enclii webhook**: `POST /api/v1/gateway/enclii` receives deployment events
  from Enclii. Bearer token auth via `enclii_webhook_secret`. Maps
  `deploy_failed`/`deploy_rollback` → `coding`, `deploy_succeeded` → `research`.
  Creates SwarmTasks and enqueues to Redis.
- **Task queue**: Redis Streams (`selva:task-stream`) with consumer groups
  (`selva-workers`).
  Dead letter queue at `selva:task-dlq` after 3 retries. Workers auto-claim
  stalled messages on startup via XAUTOCLAIM.
- **Redis pool**: `packages/redis-pool/` provides a singleton `RedisPool` with circuit
  breaker and exponential backoff. All Python services use `get_redis_pool()` instead
  of one-off `aioredis.from_url()` calls. Colyseus uses `redis-client.ts` singleton.
- **Observability**: `packages/observability/` provides shared `configure_logging()`,
  `bind_task_context()`, `init_sentry()` for Python. TypeScript uses pino via
  `packages/config/logging.ts`. All services emit structured JSON logs with
  `request_id` correlation. Prometheus metrics on `/metrics` endpoints.
- **Health endpoints**: nexus-api (`/api/v1/health/*`), gateway (`:4304/health`),
  workers (`:4305/health`), colyseus (`:4303/health`). Queue stats at
  `/api/v1/health/queue-stats`.
- WebSocket approval events use the `ConnectionManager` singleton in
  `apps/nexus-api/src/ws.py`.
- LangGraph `interrupt()` is used to pause agent execution for HITL approval.
- Synergy bonuses stack multiplicatively (see `packages/orchestrator/src/synergy.py`).
  Synergy rules support both role-based (`required_roles`) and skill-based
  (`required_skills`) requirements.
- `SwarmOrchestrator.match_agents_by_skills()` selects idle agents by skill overlap
  score. The swarms router auto-selects agents when `required_skills` is provided
  without explicit `assigned_agent_ids`.
- Agents have `skill_ids` (JSON column) and `effective_skills` (computed from
  `skill_ids` or `DEFAULT_ROLE_SKILLS` fallback). Skills flow from DB → API →
  Colyseus schema → Phaser UI badges.
- The gateway `HeartbeatService` (cron-based, `apps/gateway/`) scrapes GitHub
  events and dispatches enemy waves via WebSocket to the approvals endpoint,
  which converts them into `SwarmTask` records enqueued on Redis.
- **GitHub webhook endpoint**: `POST /api/v1/gateway/github` receives push-based
  webhooks from GitHub (PR opened/synced, issues opened, CI failures). Verifies
  `x-hub-signature-256` via `GITHUB_WEBHOOK_SECRET` env var. Maps events to
  SwarmTasks and enqueues on Redis.
- **Agent movement**: `AgentBehavior` (`apps/office-ui/src/game/AgentBehavior.ts`)
  drives agent patrol within department zones (idle), walk-to-review-station
  (waiting_approval), and freeze (working/error). 30px/s patrol, 60px/s to station.
- **Auth flow**: Next.js middleware checks `janua-session` cookie. Login page
  supports both dev bypass (dummy JWT) and Janua SSO redirect (when
  `NEXT_PUBLIC_JANUA_ISSUER_URL` is set). `apiFetch()` in `src/lib/api.ts`
  attaches Bearer token from cookie to all API calls.
- **Security middleware** (`nexus_api/middleware/security.py`): Adds CSP header
  (configurable via `csp_extra_sources` setting), `Permissions-Policy` allowing
  camera/mic for own origin (WebRTC), and standard security headers. CSP
  `connect-src` auto-includes CORS origins and `ws:/wss:`.
- **X-Selva-Tenant-Org header pattern** (v2.2.x): worker JWTs do not carry an
  `org_id` claim — they are issued once per worker, not per tenant. Every
  worker → API call therefore sends `X-Selva-Tenant-Org: <task.org_id>` to
  scope the call to the tenant whose task it is currently processing.
  `auth.py` reads the header in the dependency that resolves
  `current_user.org_id`. Missing header resolves to `org_id="platform"`
  (MADFAM-only audience). The hardcoded `"madfam-default"` fallback that
  pre-dated this pattern is gone — use
  `get_worker_auth_headers(org_id=...)` so the header always travels with
  the bearer. WebSocket upgrades strip custom headers, so workers
  additionally pass `?org_id=<uuid>` on the WS query string.
- **`agent_role` allow-list pattern** (`email_tools.py:_AGENT_ROLE_ALLOWLIST`):
  the only LLM-controllable identity field on outbound email is
  `agent_role`, constrained to `{sales, support, growth, ops, research}`.
  Any other value raises `ValueError` before send. This is the template
  for any future tool that lets the LLM choose a category-style argument:
  define a tuple/frozenset at module scope, validate at the top of
  `execute()`, raise on miss. Never trust the LLM to stay on the script.
- **CSRF middleware** (`nexus_api/middleware/csrf.py`): double-submit cookie
  pattern. Bearer-authenticated requests skip CSRF validation (Bearer tokens
  are inherently CSRF-safe). Webhook endpoints (`/api/v1/gateway/`,
  `/api/v1/billing/webhooks/`, `/api/v1/approvals/ws`, `/api/v1/health/`) are
  also exempt.
- **WebSocket rate limiting**: `MessageRateLimiter` in `ws.py` (30 msg/60s
  per client). Used by events and approvals WS endpoints. Colyseus uses
  `MessageThrottler` (30 msg/sec, exempt: `move`, `webrtc_signal`).
- **Fire-and-forget retry**: `http_retry.py` provides `fire_and_forget_request()`
  with exponential backoff (0.5s→1s→2s) and per-host circuit breaker (5
  failures→30s cooldown). Used by `task_status.py` and `event_emitter.py`.
- **Database pool**: Configurable via `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
  `DB_POOL_RECYCLE`, `DB_POOL_TIMEOUT` env vars. Pool stats at
  `/api/v1/health/pool-stats`.
- **Env validation**: `@model_validator` on both nexus-api and worker `Settings`.
  Validates URL formats, warns on insecure defaults in non-dev environments.
- **OpenTelemetry**: Optional tracing via `OTEL_EXPORTER_OTLP_ENDPOINT` env var.
  No-op when unset. W3C Trace Context propagation. Redis pool OTel spans.
- **Colyseus auth**: `onAuth` verifies JWT via `jose` + Janua JWKS.
  `filterBy(["orgId"])` for room-per-org isolation. Dev bypass preserved.
- **Playwright E2E**: `tests/e2e/` with login, dispatch, and approval specs.
  Run with `make test-e2e` (requires `npx playwright install chromium`).
- Worker graph nodes (`plan`, `implement`, `review`) use `call_llm()` from
  `selva_workers.inference` with a `ModelRouter` that auto-discovers providers
  from env vars. Graphs fall back to static logic when no LLM is configured.
- The permission matrix is evaluated by `packages/permissions/src/engine.py` before
  every tool invocation in the worker.
- **Colyseus tsconfig**: `apps/colyseus/tsconfig.json` MUST have
  `"useDefineForClassFields": false` alongside `"experimentalDecorators": true`.
  Without this, ES2022+ class field semantics override `@type` decorator
  getter/setters, causing `encodeAll()` to emit 0 bytes and clients to receive
  empty state. This is a hard requirement for `@colyseus/schema` decorators.
- **WebSocket payload**: `WebSocketTransport` is configured with
  `maxPayload: 1024 * 1024` (1 MB) because the default ws limit is too small
  when state includes 12+ agents.
- **Colyseus Scaling Recommendations**: While a large `maxPayload` prevents crashes,
  massive arrays in `OfficeStateSchema` will cause severe CPU usage during state encoding.
  Use `@filter()` annotations for lists like `chatMessages` and break rooms into
  shards per department if the agent count climbs beyond 100 globally.
- **GameEventBus caching**: `PhaserGame.tsx`'s `GameEventBus` caches the last
  emitted value per event key and replays it to late subscribers. This fixes a
  timing race where Colyseus state arrives before the Phaser `OfficeScene` is
  created.
- **Slug-based department matching**: `OfficeRoom.fetchAgentsFromApi()` matches
  API departments (which use UUID IDs) to Colyseus departments (which use
  hardcoded string IDs like `dept-engineering`) by slug. It first fetches the
  department list, then fetches detail by API UUID for each slug match.

### Multi-Player & Chat

- The Colyseus `OfficeStateSchema` uses `players: MapSchema<TacticianSchema>`
  (keyed by `client.sessionId`) instead of a single tactician. Each player has
  `sessionId`, `name`, `x`, `y`, `direction`.
- `OfficeRoom.onJoin()` creates a player entry; `onLeave()` removes it. System
  messages are broadcast to `chatMessages` on join/leave/approval events.
- `handleMovement` looks up the moving player via `state.players.get(client.sessionId)`
  so multiple players move independently.
- `chatMessages: ArraySchema<ChatMessageSchema>` holds the last 50 messages
  (user + system). The `chat` message handler validates content length (max 500).
- Office world bounds are 1600x896 (50x28 tiles at 32px).
- `OfficeScene` renders remote players as interpolated sprites with name labels.
  Local player movement is broadcast via `GameEventBus` at ~15fps with a 1px
  dead-zone to avoid flooding.
- `ChatPanel` is a collapsible React overlay (bottom-left). `T`/`/` to focus,
  `Esc` to unfocus. `GamepadManager.chatFocused` suppresses keyboard game input
  while typing.

### Tiled Map Support

- `BootScene` loads `office-default.tmj` (Tiled JSON) and an `office-tiles` image.
  `OfficeScene.create()` calls `loadTiledMap()`; on failure it falls back to the
  procedural floor + department-zone rendering that existed before.
- `TiledMapLoader.ts` parses department zones, review stations, and spawn points
  from Tiled object layers. Collision is set on an invisible `collision` layer via
  `setCollisionByExclusion([-1])`.
- The default map lives at `apps/office-ui/public/assets/maps/office-default.tmj`.

### Emotes & Reactions

- Emotes are **ephemeral** — not persisted in the Colyseus schema. The client sends
  an `emote` message with `{ type }` (one of 9 whitelisted types in
  `apps/colyseus/src/handlers/emotes.ts`). The server validates and broadcasts
  `player_emote` to all clients.
- The client renders a speech-bubble sprite above the player with a 3-second
  scale-up + fade-out tween (`OfficeScene.showEmoteBubble()`). Falls back to
  Unicode emoji text if the emotes spritesheet fails to load.
- `EmotePicker.tsx` provides a 3x3 grid UI toggled with `R`, quick-select `1-9`.
- `GamepadManager.emotePickerFocused` suppresses keyboard movement while the
  picker is open.

### Avatar Customization

- `AvatarConfig` (in `packages/shared-types/src/avatar.ts`) defines 5 properties:
  `skinTone`, `hairStyle`, `hairColor`, `outfitColor`, `accessory`.
- Config is persisted in `localStorage` via `useAvatarConfig` hook, and sent to
  the server via `avatar` message → stored as JSON string on
  `TacticianSchema.avatarConfig`.
- `AvatarCompositor.ts` generates a composite 32x32 canvas texture at runtime,
  keyed by config hash for caching. No pre-generated avatar spritesheets needed.
- `AvatarEditor.tsx` is a full-screen modal shown on first visit. Users can
  re-open it via the "Avatar" button in the top-right.
- Remote players' avatar textures are applied during `reconcileRemotePlayers()`
  based on their `avatarConfig` schema field.

### Proximity Video/Audio (WebRTC)

- **Server-side**: `proximity.ts` runs a 5Hz loop calculating which players are
  within 200px. It sends `proximity_players` messages to each client listing
  nearby session IDs. `signaling.ts` relays `webrtc_signal` messages between
  clients (SDP offers/answers, ICE candidates) — pure pass-through.
- **Client-side**: `useProximityVideo` hook manages peer connections using
  `simple-peer` (25KB). On receiving `proximity_players`, the client with the
  lexicographically lower sessionId initiates offers (deterministic, no races).
  Max 6 peers per group.
- **UI**: `VideoOverlay.tsx` renders 64px circular `<video>` bubbles (React DOM
  over Phaser canvas). `MediaControls.tsx` provides M (mute) and V (camera)
  toggle buttons.
- **STUN**: Google free STUN servers for dev. Add coturn for production.
- **Dependency**: `simple-peer@^9.11.1`, `@types/simple-peer@^9.11.8`.

### Interactive Map Objects

- `InteractableManager` (`apps/office-ui/src/game/InteractableManager.ts`) parses
  the `interactables` Tiled object layer and creates Phaser zones with overlap
  detection. Each object has an `interactType` property: `url`, `popup`,
  `jitsi-zone`, `silent-zone`, `dispatch`, `blueprint`, `desk`,
  `restricted-zone`, or `room-transition`.
- When the player overlaps an interactable zone, a `[E] label` prompt appears.
  Pressing E (buttonX) triggers the action.
- `url` and `jitsi-zone` types emit `open_cowebsite` → `CoWebsitePanel.tsx`
  renders a sliding iframe panel from the right (50vw max 640px, sandboxed).
- `popup` type emits `show_popup` → `PopupOverlay.tsx` renders a centered modal.
- `silent-zone` emits `silent_zone_enter`/`silent_zone_exit` events for
  muting proximity audio (Feature 4).
- `dispatch` type emits `open_dispatch` → `TaskDispatchPanel.tsx` renders a
  sliding form panel for dispatching swarm tasks.

### Mobile Support

- `VirtualJoystick` (`apps/office-ui/src/game/VirtualJoystick.ts`) renders at
  bottom-left: 80px base + 32px thumb, pointer drag with 0.2 deadzone.
  Only responds to left-half screen touches.
- `TouchActionButtons` (`apps/office-ui/src/game/TouchActionButtons.ts`) renders
  4 circular buttons at bottom-right: Approve (green), Deny (red), Inspect (cyan),
  Emote (yellow).
- `useTouchDetection` hook detects touch capability and orientation.
- OfficeScene applies 1.5x camera zoom on touch devices for better visibility.
- Joystick input merges with gamepad/keyboard in the update loop.

### Task Dispatch UI

- `useTaskDispatch` hook (`apps/office-ui/src/hooks/useTaskDispatch.ts`) POSTs to
  `POST /api/v1/swarms/dispatch`. State machine: idle → submitting → success | error.
- `TaskDispatchPanel` (`apps/office-ui/src/components/TaskDispatchPanel.tsx`) is a
  sliding panel (right side, w-80) with description, graph type selector, optional
  agent assignment, and optional skill requirements.
- Entry points: (1) walk to a dispatch station on the map → press E, (2) click
  "+ New Task" button in the DashboardPanel header.
- Dispatch stations are `interactables` objects in `office-default.tmj` with
  `interactType: "dispatch"` at (304,296) and (544,296) in the central corridor.
- Mutual exclusion: opening dispatch panel closes the dashboard panel.
- Uses `chat-focus` gameEventBus event to suppress keyboard game input while typing.

### Map Scripting API (Feature 9)

- `ScriptBridge` (`apps/office-ui/src/game/scripting/ScriptBridge.ts`) manages
  hidden sandboxed iframes for map scripts. Scripts defined via `scriptUrl`
  property on the Tiled map. Communication via `postMessage` with command whitelist.
- `ScriptAPI` (`apps/office-ui/src/game/scripting/ScriptAPI.ts`) defines the
  `AS.*` namespace injected into script iframes: `AS.chat.sendMessage()`,
  `AS.camera.moveTo()`, `AS.player.moveTo()`, `AS.ui.openPopup()`,
  `AS.ui.openCoWebsite()`, `AS.onPlayerEntersArea()`, `AS.onPlayerLeavesArea()`.
- `InteractableManager` emits `zone_enter`/`zone_leave` events on the gameEventBus;
  `OfficeScene` forwards these to `ScriptBridge.notifyAreaEvent()`.
- Lifecycle: created on map load if `scriptUrl` property exists, destroyed on
  scene shutdown.

### Click-to-Move & Pathfinding

- `Pathfinder` (`apps/office-ui/src/game/Pathfinder.ts`): A* pathfinding on
  the Tiled collision grid. Manhattan heuristic, 4-directional, 2000 iteration
  safety cap. Falls back to direct line when no collision layer.
- `pointerup` handler in `OfficeScene.createTactician()` computes path on left
  click, spawns fading indigo marker at destination.
- Click path followed in `update()` via normalized direction injection into
  `stickX`/`stickY`. Keyboard/gamepad input immediately cancels click path.
- `GamepadManager.isFocused()` suppresses clicks while chat/emote picker open.

### Follow Player Camera

- `F` key follows nearest remote player. Camera switches to track their sprite.
- ESC or manual movement cancels follow.
- `followLabel` text overlay shows "Following: [name]" while active.
- `follow-status` gameEventBus event updates HUD badge in React.

### Explorer Mode

- `Tab` toggles explorer mode: zooms camera out to show full map, enables
  scroll-to-pan with movement sticks, disables player movement.
- `Tab` or `ESC` exits explorer mode, restoring previous zoom + camera follow.
- `explorer-mode` gameEventBus event updates HUD badge in React.
- Agent behavior continues running during explorer mode.

### Player Status (Away/Busy/DND)

- `TacticianSchema.playerStatus` (`@type("string")`, default `"online"`):
  synced via Colyseus to all clients. Values: `online`, `away`, `busy`, `dnd`.
- `handleStatus` (`apps/colyseus/src/handlers/status.ts`): validates against
  whitelist, follows `emotes.ts` handler pattern.
- `usePlayerStatus` hook: 5-min auto-away timer (30s check interval),
  auto-restore on activity (mousemove/keydown/pointerdown).
- `StatusSelector` component: dropdown with colored dots (green/amber/red/grey).
- Status dot rendered next to remote player name labels in `OfficeScene`.
- DND status suppresses proximity video connections in `useProximityVideo`.

### Personal Desks

- `desk` interactable type in `InteractableManager` with `assignedAgentId`
  property parsed from Tiled objects.
- `AgentBehavior.setDeskPosition()` overrides agent home position so idle
  agents patrol around their assigned desk.
- Desk positions wired in `OfficeScene.onStateUpdate()` after agent reconciliation.
- `DeskInfoPanel` component shows agent name, role, status, and skills on
  desk interaction. Emits via `open_desk_info` gameEventBus event.

### Screen Sharing

- `toggleScreenShare()` in `useProximityVideo`: uses `getDisplayMedia()` to
  capture screen, replaces video track on all active peers via
  `RTCRtpSender.replaceTrack()`. Auto-stops on `track.onended` (browser UI).
- Screen share button (S key) in `MediaControls.tsx`.
- Local video preview shows "Screen" label at 128px when sharing.

### Local Recording

- `useRecording` hook (`apps/office-ui/src/hooks/useRecording.ts`): mixes local
  + remote audio via `AudioContext.createMediaStreamDestination()`, records with
  `MediaRecorder` (webm/vp9+opus). Downloads on stop. Browser-local only.
- `RecordingControls` component: red pulsing record button with duration timer.
- States: `idle` | `recording` | `processing`.

### Locked Bubbles

- Server-side locked groups in `proximity.ts`: `lockBubble()` captures current
  nearby players into a locked set. Locked members only see each other in
  proximity calculations. Outsiders cannot join locked groups.
- `lock_bubble`/`unlock_bubble` Colyseus messages. Any member can unlock.
- `removeFromLockedGroups()` called on player leave. Groups dissolve when < 2.
- Lock button (L key) in `MediaControls.tsx` with amber highlight when active.

### Area Access Restrictions

- `restricted-zone` interactable type with `requiredTags` property (comma-separated).
- `InteractableManager.setPlayerTags()` sets the player's tags for access checks.
- Players without required tags are pushed out of restricted zones.
- `access_denied` gameEventBus event emitted once per zone entry attempt.

### Companions/Pets

- `TacticianSchema.companionType` (`@type("string")`, default `""`): synced
  via Colyseus. Values: `""`, `cat`, `dog`, `robot`, `dragon`, `parrot`.
- `handleCompanion` handler validates against whitelist (follows emotes pattern).
- `CompanionBehavior` class follows owner with lag (speed 180, follow distance
  28px, lerp factor 0.08). Rendered as 8x8 colored rectangles in OfficeScene.
- `reconcileCompanionSprite()` in OfficeScene creates/updates/removes companions
  during remote player reconciliation.
- Companion selection tab in `AvatarEditor.tsx`. Persisted to localStorage.
- Companion sprite data in `packages/shared-types/src/sprite-data/companions.json`.

### Megaphone/Broadcast

- One speaker at a time (first-come-first-served). Module-level state in
  `handlers/megaphone.ts`.
- `megaphone_start`/`megaphone_stop` messages. `releaseMegaphone()` on disconnect.
- Speaker's sessionId injected into ALL players' nearbySessionIds in
  `startProximityLoop()`, enabling room-wide audio.
- `MegaphoneControls.tsx` component with pulsing broadcast indicator.

### Multi-Room Navigation

- `room-transition` interactable type in InteractableManager. `content` field
  specifies target room ID.
- `room_transition` gameEventBus event updates URL `?map=` parameter.
- `RoomNavigator.tsx` dropdown component (bottom-right) with 4 predefined rooms.
- Room switching reloads the Tiled map via `?map=<name>` URL parameter.

### Noise Suppression

- `audio-processor.ts` utility: WebAudio filter chain with highpass(80Hz) +
  DynamicsCompressor. Returns processed output stream.
- `toggleNoiseSuppression()` in useProximityVideo: lazy-imports the audio
  processor, replaces audio track on all peers via `replaceTrack()`.
- Toggle button (N key) in MediaControls with emerald highlight when active.

### UI/UX Infrastructure

- **ErrorBoundary** (`apps/office-ui/src/components/ErrorBoundary.tsx`) wraps the
  main page content. Class component with fallback UI + retry button.
- **Toast system**: `ToastProvider` wraps the app in `page.tsx`. Use
  `useToast().addToast(message, severity)` from any component. Toasts auto-dismiss
  after 5s with a 200ms exit animation (`animate-slide-out-right`). Toasts have a
  `dismissing` flag for exit animation state. Severity: `success`, `error`,
  `warning`, `info`.
- **Focus trapping**: `useFocusTrap(active)` hook returns a ref. Applied to
  `AvatarEditor`, `PopupOverlay`, `TaskDispatchPanel`. Traps Tab cycling and
  restores previous focus on close.
- **Loading screen**: `BootScene.preload()` renders a progress bar with percentage
  during asset loading. Loading text pulses (alpha 0.7→1). Rotating tips cycle
  below the bar every 2.5s ("Walk near agents to interact...", etc.).
- **Help overlay**: Press `?` to toggle. Has backdrop, `[X]` close button, and
  gamepad mappings alongside keyboard shortcuts.
- **Design system tokens** in `tailwind.config.ts`:
  - Semantic colors: `semantic-success`, `semantic-error`, `semantic-warning`,
    `semantic-info`
  - Z-index scale: `z-hud` (20), `z-video` (30), `z-backdrop` (40),
    `z-modal` (50), `z-toast` (60)
  - Typography: `text-retro-xs` (7px), `text-retro-sm` (8px),
    `text-retro-base` (10px), `text-retro-lg` (12px)
  - Button `xs` size variant in `packages/ui/src/button.tsx`
- **Font loading**: Press Start 2P loaded via `next/font/google` in `layout.tsx`
  (CSS variable `--font-pixel`). No HTTP `@import` in globals.css.
- **iframe sandbox**: `CoWebsitePanel` uses `allow-scripts allow-forms allow-popups`
  (no `allow-same-origin`).
- **Global focus indicators**: `*:focus-visible` outline set in `globals.css`.
- **Responsive panels**: `ChatPanel`, `DashboardPanel`, `TaskDispatchPanel` use
  `w-full max-w-80 sm:w-80` for mobile.
- **Responsive game fonts**: `responsiveFontSize(base)` in `OfficeScene.ts` scales
  with viewport width.
- **Touch feedback**: VirtualJoystick thumb alpha (0.4 idle/0.9 active),
  TouchActionButtons scale+alpha on press, 48px min touch targets.
- **CSS animation vocabulary** in `globals.css` (`@layer utilities`):
  - `animate-slide-in-right` / `animate-slide-out-right` (300ms/200ms)
  - `animate-fade-in` / `animate-fade-in-up` (200ms/250ms)
  - `animate-pop-in` with spring overshoot (300ms cubic-bezier)
  - `animate-pulse-border` for glowing borders (2s infinite)
- **`.retro-btn` class** in `globals.css`: hover=translateY(-1px)+glow,
  active=translateY(1px)+inset shadow. Applied to dashboard toggle, avatar
  button, chat toggle, emote button, and avatar editor action buttons.
- **`.retro-panel:hover` glow**: subtle indigo box-shadow expansion on hover.
- **CRT scanline overlay**: `.scanline-overlay::after` in `globals.css` with
  `repeating-linear-gradient` at 3% opacity. Applied to `<main>` in `page.tsx`.
- **Phaser post-FX**: CRT vignette on main camera, gated behind
  `ENABLE_POST_FX` constant in `OfficeScene.ts`.
- **Particle system**: Ambient dust motes (1 per 800ms, ADD blend, alpha
  0→0.3), tactician walk dust trail, agent status particles (cyan sparkles
  for working, red wisps for error). All gated behind `ENABLE_PARTICLES`.
  Runtime-generated 2x2 (`particle-dot`) and 3x3 (`particle-dust`) textures
  in `BootScene.ts`.
- **Department zone ambient pulse**: alpha-breathing tween (0.2→0.35) on zone
  overlays, staggered by index.
- **Agent status halos**: colored circle beneath each agent (slate=idle,
  cyan=working, amber+pulse=waiting_approval, red=error). Stored in
  `AgentSprite.statusHalo`.
- **Agent idle breathing**: subtle scaleY tween (1.0→1.04, 2s) on idle agents.
  Paused when status changes away from idle.
- **Agent name label backgrounds**: black rectangle at 0.5 alpha behind name
  text for readability over zone colors. Both `nameLabel` and `nameBackground`
  are stored in `AgentSprite` and repositioned each frame alongside the sprite.
- **Review station glow**: pulsing alpha tween + `preFX.addGlow()` when
  `pendingApprovals > 0`. Cleared when 0.
- **Tactician spawn-in effect**: scale 0.5→1.0 + alpha 0→1 with Back.easeOut,
  indigo particle burst (8 particles).
- **Chat bubbles**: local messages right-aligned (`bg-indigo-900/50`), remote
  left-aligned (`bg-slate-800/60`), system centered italic. Staggered
  `animate-fade-in-up`.
- **Dashboard enhancements**: backdrop overlay when open (click-to-close),
  kanban cards with left-border color by status + hover translate, department
  stat bars (cyan agents bar, amber tasks bar), staggered fade-in.
- **HUD count animation**: agent count and approval count wrapped in
  `<span key={count}>` with `animate-pop-in` (re-mounts on value change).
  Approval badge gets `animate-pulse` + `animate-pulse-border` when count > 0.
- **Functional minimap**: `Minimap` sub-component in `HUD.tsx` renders to
  128x96 `<canvas>`. Draws department zones as colored rectangles, agents as
  2px status-colored dots (idle=slate, working=cyan, waiting_approval=amber,
  error=red), player as 3px indigo dot with glow ring. Fed by `playerPosition`
  state from `page.tsx` (updated on `handlePlayerMove`).
- **Avatar editor canvas preview**: real 32x32 composited avatar drawn at 4x
  scale (128x128) using pure-canvas `drawAvatar()` utility extracted from
  `AvatarCompositor.ts` logic. Updates on every config change.
  `imageSmoothingEnabled = false` + CSS `image-rendering: pixelated`.
  Modal uses `retro-panel pixel-border-accent` with `animate-pop-in`.
- **Color swatch feedback**: `active:scale-90`, selected swatches get
  `ring-2 ring-indigo-400 ring-offset-2 ring-offset-slate-900`.
- **EmotePicker pop-in**: outer container `animate-pop-in`, each button
  staggered `animate-fade-in-up` (30ms), `hover:scale-110 active:scale-95`.
- **Video overlay animations**: peer bubbles `animate-pop-in` on connect.

## Sprite Assets

- Pre-generated pixel-art PNGs live in `apps/office-ui/public/assets/` (sprites,
  tilesets, UI icons). These are committed to the repo.
- Regenerate with `make generate-assets` (runs `scripts/generate-assets.js` using
  `@napi-rs/canvas`).
- **Pixel-data template system**: All sprite art is defined as 2D arrays of
  single-character palette tokens (body, hair, accessories) or direct hex colors
  (emotes, tiles, icons) in `packages/shared-types/src/sprite-data/*.json`.
  - `body.json` — 12 body templates (4 directions x 3 walk frames, 32x32)
  - `hair.json` — 16 hair overlays (4 styles x 4 directions)
  - `accessories.json` — 10 accessories (4 player + 6 agent role)
  - `emotes.json` — 9 pictographic emotes (32x32)
  - `tiles.json` — 8 tiles (32x32), `icons.json` — 4 icons (16x16)
  - `palette.json` — token definitions, `resolve-colors.ts` — avatar config to
    color map resolver with `darken()`/`lighten()` utilities
- **Shared renderers** (`renderPixelData()` + `composeLayers()`):
  - `scripts/sprite-data/renderer.js` — Node.js build-time (used by generate-assets)
  - `apps/office-ui/src/game/sprite-data/renderer.ts` — browser/Phaser runtime
- `AvatarCompositor.ts` and `AvatarEditor.tsx` both use the shared renderer +
  `resolveColorMap()` to composite body + hair + accessory layers. No duplicated
  drawing logic.
- `BootScene.ts` loads sprite files with automatic canvas-rectangle fallback if any
  PNG fails to load. Department zone overlays are always canvas-generated. The emote
  spritesheet (`emotes.png`, 9 frames at 32x32) is also loaded here. Particle
  textures (`particle-dot` 2x2, `particle-dust` 3x3) are runtime-generated.
- `OfficeScene.ts` plays walk animations for the Tactician (4 dirs x 3 frames) and
  idle/working animations for agents. Post-FX, particles, and ambient effects are
  gated behind `ENABLE_POST_FX` and `ENABLE_PARTICLES` constants.

### Palette Presets & Color Utilities

- **Palette presets** (`packages/shared-types/src/sprite-data/palette-presets.ts`):
  10 named presets (default, cyberpunk, forest, desert, arctic, ocean, volcano,
  neon, monochrome, pastel). Each defines environment colors (floor, wall, dept
  zones, review station), optional `avatarTint`, and optional `outfitOverrides`.
- **Color utilities** in `resolve-colors.ts`: `darken()`, `lighten()`,
  `saturate()`, `hueShift()`, `tint()` — all pure hex-in/hex-out.
- `resolveEnvironmentColorMap(presetName)` returns environment colors for a preset.
- `resolveThemeColorMap(presetName, avatarConfig)` applies the preset's avatarTint
  over standard avatar colors (15% tint factor, 7.5% on skin).
- All presets tested for minimum contrast ratios (review station vs floor >= 3:1,
  wall vs floor >= 1.2:1).

### Sprite Variant Generator

- `scripts/generate-variants.js` — generates themed sprite sheets per
  role × palette preset. CLI: `--presets`, `--roles`, `--output`.
- `scripts/generate-tile-variants.js` — generates themed tilesets per preset.
- `scripts/sprite-data/variation-combiner.js` — shared layer composition logic
  with tint support for variant generation.
- `scripts/post-process-assets.sh` — optional ImageMagick 2x/4x upscale + WebP.
  Gracefully skips if ImageMagick not installed.
- `generate-assets.js` extended with `--variants` (all presets) and
  `--preset <name>` (single themed tileset) flags. Tileset is now 512x128
  (16 columns x 4 rows = 54 tiles) using both hex colors and palette tokens.
- `scripts/sprite-data/tile-definitions.js` generates 46 new tiles
  programmatically (walls, floors, furniture, stations, decorations) using
  palette tokens (FL, WL, WH, FN, etc.) for theme-ability.
- `scripts/generate-office-map.js` constructs the hand-crafted 50x28
  office-default.tmj with 9 layers (floor, walls, furniture, decorations,
  collision, departments, review-stations, interactables, spawn-points).
- Output: `apps/office-ui/public/assets/sprites/variants/<preset>/` and
  `apps/office-ui/public/assets/tilesets/variants/`.

### WFC Procedural Map Generation

- **Package**: `packages/map-gen/` (`@selva/map-gen`)
  - `src/wfc.ts` — core WFC with `WFCGrid.run()`, `observe()`, `collapse()`,
    `propagate()`, backtracking retries, seeded PRNG (`createRng()`).
  - `src/rules.ts` — adjacency rules for office meta-tiles (wall, corridor,
    dept_N, dept_wall_N). `metaTileToTileId()` maps to tileset indices.
  - `src/constraints.ts` — department region detection, object placement
    (review stations, dispatch stations, spawn points), map validation.
  - `src/tmj-writer.ts` — outputs valid `.tmj` matching `TiledMapLoader.ts`
    layer contract: floor, departments, review-stations, interactables,
    spawn-points.
- **CLI**: `scripts/generate-map.js` — `--seed`, `--departments`, `--width`,
  `--height`, `--output`. Default: 40x22, 4 depts, seed 42.
- **Hand-crafted map**: `scripts/generate-office-map.js` — `--output`. Generates
  50x28 map with 4 dept rooms, corridors, lobby, blueprint nook, furniture
  clusters, collision layer. Default: `office-default.tmj`.
- **BootScene integration**: `?map=<name>` URL parameter loads
  `/assets/maps/<name>.tmj`. Default: `office-default`.
- Existing `loadTiledMap()` fallback handles any schema issues with generated maps.

### Pixelact UI Components

- **Scoped namespace**: `.pixelact` class in `globals.css` defines CSS variables
  (`--pixelact-bg`, `--pixelact-fg`, etc.) and `.pxa-btn`/`.pxa-input` styles
  with 3D pixel press effects. Avoids collision with `.retro-btn`/`.pixel-border`.
- **Pixelact colors** in `tailwind.config.ts`: `pixelact-bg`, `pixelact-fg`,
  `pixelact-border`, `pixelact-primary`, etc. Map to CSS variables.
- **Pixelact shadows**: `shadow-pixelact-raised` (3D raised) and
  `shadow-pixelact-pressed` (inset pressed).
- **PixelButton** (`packages/ui/src/pixelact/pixel-button.tsx`): CVA variants
  (default/secondary/destructive/success/ghost) × sizes (default/sm/lg).
- **PixelInput** (`packages/ui/src/pixelact/pixel-input.tsx`): styled input with
  inset shadow and focus border.
- **shadcn config**: `packages/ui/components.json` configures shadcn with
  Pixelact registry URL for future `npx shadcn@latest add` usage.
- Exported from `packages/ui/src/index.ts`.
- **Preview tool**: `scripts/preview-tileset.js` generates an HTML catalog of
  all tiles across all presets at 4x scale.

### Full-Stack Observability ("The All Seeing Eye")

- **TaskEvent model** (`models.py`): INSERT-only event record with task_id,
  agent_id, event_type, event_category, node_id, graph_type, payload,
  duration_ms, provider, model, token_count, error_message, request_id,
  org_id, created_at. Migration `0011`.
- **Event emitter** (`apps/workers/selva_workers/event_emitter.py`):
  `emit_event()` — fire-and-forget POST to `/api/v1/events` + Redis PUBLISH
  to `selva:events`. 2s HTTP timeout. Follows `task_status.py` pattern.
  `@instrumented_node` decorator wraps graph nodes to emit `node.entered`,
  `node.exited`, `node.error` events with `duration_ms` measurement.
- **Worker instrumentation**: All 6 graph types (coding, research, CRM,
  deployment, puppeteer, meeting) decorated with `@instrumented_node` on
  every node function. `__main__.py` emits `task.started`, `task.completed`,
  `task.failed`, `task.timeout` events. `inference.py` emits `llm.response`
  events with provider, model, token_count, duration_ms.
- **Events REST API** (`routers/events.py`): `POST /api/v1/events` (no auth,
  worker-to-API), `GET /api/v1/events` (paginated, filtered by task_id,
  agent_id, event_type, event_category, since, until),
  `GET /api/v1/events/tasks/{id}/timeline` (chronological with aggregates).
  `WS /api/v1/events/ws` (initial 50-event batch + real-time relay via
  `event_manager` ConnectionManager singleton).
- **Server-side emission**: `swarms.py` emits `task.dispatched` on dispatch,
  `approvals.py` emits `approval.approved`/`approval.denied` on decision.
  Uses `emit_event_db()` (direct DB insert, no HTTP).
- **Task board API**: `GET /api/v1/swarms/tasks/board` — DB-backed kanban
  with columns (queued/running/completed/failed), aggregated event data
  (duration_ms, total_tokens, event_count), agent name resolution.
- **Metrics API** (`routers/metrics.py`): `GET /api/v1/metrics/dashboard` —
  agent utilization %, task throughput (status counts, avg duration),
  approval latency (avg, pending), cost breakdown (by provider/model),
  error rate, trend sparklines (hourly buckets), recent errors. Period
  options: 1h, 6h, 24h, 7d, 30d.
- **OpsFeed component** (`OpsFeed.tsx`): Sliding panel (left side) with
  real-time event stream via `useEventStream` WebSocket hook. Category
  filter pills, text search, auto-scroll, color-coded event cards.
  Capped at 500 in-memory events. "Load more" pagination.
- **Enhanced DashboardPanel**: Rewritten to use `useTaskBoard` hook (DB-backed)
  instead of `deriveTasksFromAgents()` (snapshot-derived). TaskCard shows
  description, graph_type badge, agent names, duration, token count, event
  count. Click-to-expand timeline view shows chronological events.
- **MetricsDashboard component** (`MetricsDashboard.tsx`): Full-screen modal
  with period selector, stat cards (utilization, throughput, approval queue,
  error rate), SVG sparklines (zero-dependency), CSS bar chart for cost
  breakdown, task status breakdown, recent errors list.
- **Page integration**: "Ops Feed" and "Metrics" buttons in top-left HUD.
  OpsFeed opens left panel; MetricsDashboard opens full-screen modal.
- **Shared types** (`packages/shared-types/src/events.ts`): EventCategory,
  EventType, TaskEvent, TaskTimeline, TaskBoardItem, TaskBoardResponse,
  TrendPoint, MetricsDashboard TypeScript interfaces.
- **CSRF**: `/api/v1/events/` and `/api/v1/events/ws` exempt from CSRF
  middleware (worker-to-API calls don't carry cookies).

<!-- END LEGACY_CLAUDE_IMPORT -->
