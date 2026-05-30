# Selva Office — Product Roadmap

> **Selva** is the autonomous virtual office product by **Innovaciones MADFAM SAS de CV**.
> It runs at `selva.town` and integrates with the full MADFAM ecosystem.
> _The legacy "AutoSwarm Office" name is retained only inside historical migration
> identifiers and a few infra namespaces. The product, repo, and brand are Selva._
>
> **Need to know what's blocked on a human decision right now?** See
> [docs/OPERATOR_BACKLOG.md](docs/OPERATOR_BACKLOG.md) — priority-
> ordered items, each with what / why / owner / unblocks / cross-refs.
>
> **North star — full autonomous digital operations?** See
> [docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md)
> — phased program (Phases 0–6) toward 100% autonomous, revenue-generating,
> campaign-planning, compliance-grade, multi-product orchestration.

---

## Autonomous Operations Program (2026-05-30)

Canonical plan: [docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md).

| Phase | Focus | Horizon | Gate |
|-------|-------|---------|------|
| **0** | Ops foundation (OTel, Sentry, Stripe map, k6, DR, staging) | 2–3 wk | verify-doc-truth + staging smoke green |
| **1** | Closed revenue loop live (CRM → email → Stripe → CFDI) | 3–4 wk | One attributed paid conversion |
| **2** | Tulana campaign orchestration | 4–6 wk | Tulana → Selva → Phynd → Tulana loop |
| **3** | Phygital E2E graph | 6–8 wk | Recorded design → invoice demo |
| **4** | Compliance-grade (SAT, LFPDPPP, CDC, residency) | 6–10 wk | Audit trail + consent + region answerable |
| **5** | Multi-tenant GTM at scale | 8–12 wk | SSO, white-label, paying Karafiel wedge |
| **6** | Phase 6 — Autonomy graduation (ASK → ALLOW) | Ongoing | Per-lane 30d clean-run policy |

**Baseline → north star:** MADFAM platform slice ~85–90%; production-truthful Selva ~88–92%; full autonomous digital ops ~40–55%. Target ~95%+ engineering completion in 6–9 months; 100% includes GTM traction (Phase 5).

Factory-as-a-Product (F1–F5) and Enterprise Autonomy (E1–E6) sections below map into program Phases 1–5 — use the program doc for sequencing and exit gates.

---

## Current Status: v2.3.0 + staging bootstrap (2026-05-30) ✅

> Supersedes v2.2.0 "Outbound Voice Mode + Consent Ledger". 28 PRs in
> 24h on 2026-05-04 closed every in-repo Phase 1, Phase 2, and Phase 3
> item that didn't require an operator decision. Workers + packages
> mypy 0; audit-trail emit on all 37 mutation sites; RLS strict mode +
> `tenant_session()` + `admin_session()` helpers; Idempotency-Key on
> 10 mutation endpoints; secret rotation script + per-period
> consent-ledger key tracking; W3C trace context propagation;
> Prometheus rules + Grafana dashboard for SLOs; 5 architecture RFCs
> landed (#0017, #0018, #0019, #0020, #0021). See
> [CHANGELOG.md `[2.3.0]`](CHANGELOG.md) for the full list.

| Metric | Value | Source |
|--------|-------|--------|
| Built-in tools | 268 registered (`get_builtin_tools()`) | `uv run python -c "from selva_tools.builtins import get_builtin_tools; print(len(get_builtin_tools()))"` |
| Workflow graphs | 12 (accounting, billing, coding, crm, deployment, intelligence, meeting, operations, project, puppeteer, research, sales) | `apps/workers/selva_workers/graphs/*.py` |
| Ecosystem adapters | 6 (Karafiel, Dhanam, PhyndCRM, Tezca, Crawler, A2A) | `packages/tools/src/selva_tools/adapters/` |
| Skills (en + es-MX) | 17 (15 tenant + meta) | `packages/skills/skill-definitions/` |
| Alembic migrations | 32 (latest 0030 — consent_ledger_signing_keys) | `apps/nexus-api/alembic/versions/*.py` |
| Test files | 828 (pytest + vitest + playwright) | `find apps packages tests -name "test_*.py" -o -name "*.test.ts" -o -name "*.spec.ts"` |
| Open architecture RFCs | 5 (#0017 image digests, #0018 A2A external tenant, #0019 CDC audit topic, #0020 data residency, #0021 multi-region failover) | `docs/rfcs/*.md` |
| Python type safety | mypy=0 across all 3 trees (nexus-api, workers, packages) — CI ratchet at 0 | `.github/workflows/ci.yml` |
| Python lint | 0 errors | `uv run ruff check .` |
| Messaging gateways | 18 channels | `packages/tools/src/selva_tools/gateways/` |
| Solarpunk visual phases | 4/4 complete | — |
| PWA installable | Yes | — |
| Tool/skill audience boundary | Platform vs Tenant (shadow mode) | `packages/permissions/src/selva_permissions/audience.py` |
| Outbound voice modes | 3 (`user_direct`, `dyad_selva_plus_user`, `agent_identified`) + ledger | `packages/tools/src/selva_tools/builtins/email.py` |

---

## Roadmap to Production-Truthful (post v2.2.0)

After the v2.2.x security + UX remediation pass landed (see commits
on chore/full-remediation; merged to main as one combined PR), the
platform is roughly 45-55% of "fully production stable + data-truthful."
The remediation closed the most weaponizable holes (worker token
cross-tenant bypass, webhook fail-open, ledger forgery, email From:
spoofing, artifact path traversal). The remaining 45% is harder:
schema migration discipline, cross-service alignment, operational
maturity, and real load + chaos testing.

This roadmap sequences the next 6-10 weeks of work to close that gap.

### Phase 1 — high-leverage, low-design (1-2 weeks)

These are mechanical fixes blocked only by execution time. Each is
foundationally one-line dangerous if left undone.

- ~~**Postgres RLS rollout**~~ — DONE (Phase 1 layer). Migration 0025
  enables RLS on 18 tenant-scoped tables with policies that filter by
  `current_setting('app.current_org_id', true)`. `database._set_session_org_id`
  sets the variable from the auth context's `org_id_var` ContextVar on
  every request via `get_db`. Permissive escape hatch (NULL/empty
  session org → policy permits) covers Alembic / healthchecks / demo
  paths. SQLite test paths no-op cleanly. Closes the entire class of
  "missed `.where(org_id == tenant.org_id)`" bugs at the database
  layer. New Phase 1.5 entry below tightens the escape hatch after
  production observation.
- ~~**12 remaining webhook handlers hardened**~~ — DONE for 11 of them
  (Telegram, Slack, Matrix, Mattermost, Twilio SMS, DingTalk, Feishu,
  WeCom, Weixin, BlueBubbles, HomeAssistant) via the new `_require_secret()`
  helper at the top of each handler. Each now returns 503 on empty
  secret, mirroring the v2.2.x Discord/WhatsApp/generic pattern. New
  Settings fields (`dingtalk_app_secret`, `feishu_app_secret`,
  `wecom_token`, `weixin_app_token`, `bluebubbles_password`, `ha_token`)
  give those handlers a single source of truth instead of `getattr`
  fallback. 11 new parameterized regression tests pin the contract.
  (12th item — `email_inbound` — uses an allow-list pattern, not a
  shared secret; intentionally left for a separate PR with its own
  threat model review.)
- ~~**Gateway → Celery SSRF gap**~~ — DONE (defense-in-depth).
  `run_acp_workflow_task` now re-validates the target URL at
  task-start time using the same `_validate_webhook_url` the gateway
  used at admission. Narrows the DNS-rebinding window from minutes
  (queue dwell) to seconds (Celery dequeue). The workflow's internal
  `requests.get` inside `ACPAnalystNode` is still vulnerable to a
  fast-rebinding attacker — Phase 2 follow-up threads pre-resolved
  IP through the workflow node's HTTP call sites.
- ~~**`@colyseus/core` 0.17 migration**~~ — DONE. `Room<{ state: OfficeStateSchema }>`
  metadata-object pattern + `onLeave(client, code?: number)` signature.
  Local `RoomOptions` interface renamed to `OfficeJoinOptions` to avoid
  collision with the colyseus base type. 166/166 colyseus tests pass.
- ~~**Office-ui WebSocket clients add `?token=`**~~ — DONE.
  `useEventStream` and `useApprovals` now read the JWT from
  `getSessionToken()` and append `?token=<jwt>` to the WS URL.
  Connection is gracefully skipped when no token is available
  (unauthenticated path or demo mode). 2 new tests pin the contract.
- ~~**Stripe webhook handler**~~ — DONE. Scaffold at
  `/api/v1/stripe/webhook` verifies signatures via
  `stripe.Webhook.construct_event` with 300s replay-tolerance.
  Fail-closed on missing `STRIPE_WEBHOOK_SECRET` (503).
  Settings validator refuses empty secret when
  `FEATURE_STRIPE_MXN_LIVE=true` in production. **Per-event handlers
  shipped** in PR #116: `customer.subscription.{created,updated,deleted}`
  + `invoice.{paid,payment_failed}` mirror state into `tenant_configs`
  via migration 0027 (`stripe_customer_id` UNIQUE+indexed lookup),
  refresh cached tier limits, and emit `billing.invoice_paid` /
  `billing.payment_failed` task events. 22 regression tests pin the
  contract. Operator follow-up: configure Stripe price→tier mapping in
  **Dhanam** and point webhooks at Selva `/api/v1/billing/webhooks/dhanam`
  before enabling live billing (`BILLING_VIA_DHANAM=true`, default).
- **Production secrets provisioned** — `WORKER_API_TOKEN`,
  `CONSENT_LEDGER_SIGNING_SECRET`, `COLYSEUS_SERVICE_TOKEN` all need
  strong values in staging + prod. Settings validators now refuse
  weak / dev defaults in production environment.
- **OTel exporter actually wired** — `OTEL_EXPORTER_OTLP_ENDPOINT` is
  read but no-op when unset. Pick a backend (Honeycomb / Tempo /
  Datadog), wire the env var, get traces flowing for at least one
  request path end-to-end. **Vendor decision pending operator review** —
  see [docs/OBSERVABILITY_VENDOR_SELECTION.md](docs/OBSERVABILITY_VENDOR_SELECTION.md)
  (recommendation: Grafana Cloud Free → Pro for traces+logs+metrics).
- **Sentry DSN per service** — `init_sentry()` exists but DSNs are
  missing from `.env.example`; verify it's actually catching errors.
  Add source-map upload for office-ui in CI. **Vendor decision pending
  operator review** — same doc as above (recommendation: stay with
  Sentry Team plan EU region, $26/mo).

### Phase 1.5 — RLS tightening (after 1-2 weeks of production observation)

- **Audit every code path that runs without `org_id_var` set** — the
  Phase 1 RLS policies use a permissive escape hatch (NULL/empty
  session org → policy permits) so Alembic / healthchecks / demo /
  unauthenticated paths keep working. After observing production
  query patterns, enumerate every legitimate "no tenant context"
  path and either: (a) set an explicit context (e.g. "platform" for
  MADFAM-internal queries), or (b) document each one.
  **First fix landed (PR #114)**: `POST /api/v1/swarms/tasks/reap-stale`
  was silently scoped to one org because it inherited the caller's
  `org_id` via `Depends(get_db)` and the permissive RLS policy then
  filtered to that org only. Now requires a service/worker/platform/admin
  role and explicitly resets `app.current_org_id = ''` for the
  cross-tenant SELECT. The Phase 1.5 audit doc tracks the rest of the
  endpoints that need similar treatment before the permissive escape
  hatch is removed (see `docs/RLS_PHASE_1_5_AUDIT.md`).
- **Tighten the policies** — remove the `IS NULL OR = ''` branch and
  require an explicit session org on every query against a tenant
  table. Migrations should set `app.current_org_id = 'system'` and
  the policy should permit `'system'` as the platform-internal
  bypass.
- **`FORCE ROW LEVEL SECURITY`** — apply policies to the table owner
  role too, so a compromised superuser can't bypass via direct SQL.
  Requires migration scripts to use a non-owner role or explicit
  `SET ROLE` to a non-bypass role.

### Phase 2 — mid-leverage, more design (next month)

- **Tenant onboarding UI for outbound identity** — DONE (migration 0026).
  `outbound_user_email`, `outbound_user_name`, `outbound_agent_slug`
  are now first-class `tenant_configs` columns with a PUT endpoint
  (`PUT /api/v1/onboarding/tenant-identity`) and an office-ui form
  at `/settings/outbound-identity`. The GET endpoint prefers the new
  columns over the legacy fallback chain
  (brand_name / razon_social / tenant_identities); the legacy chain
  still applies when the new columns are NULL so existing tenants
  remain unaffected.
- **Schema codegen TS↔Python** — 29 Python ORM models, ~7 TypeScript
  shared-types interfaces. Frontend hooks call uncovered endpoints with
  `Record<string, unknown>` ad-hoc shapes. Pipeline: `datamodel-code-generator`
  generates JSON Schema → `json-schema-to-typescript` emits TS. CI fails
  on drift.
- **AUDIENCE_FILTER_ENABLED=true** — currently shadow-mode (default
  `false`). After 24-48h observation in production confirms the
  shadow-block log is empty, flip the gate so platform-only tools
  actually refuse tenant invocations. **Rollout plan ready** — see
  [docs/AUDIENCE_FILTER_ROLLOUT.md](docs/AUDIENCE_FILTER_ROLLOUT.md)
  (synthetic-exercise procedure pre-launch; full 48h soak when first
  paying tenant onboards).
- ~~**Mypy baseline elimination — nexus-api**~~ — DONE (waves 1, 1.5, 3).
  144 → 0 in `apps/nexus-api/`. CI ratchet at `MAX_MYPY_ERRORS=0`.
  Surfaced 4 latent bugs along the way (wrong `adapters.compliance`
  import path, missing `await` on `KarafielAdapter.get_cfdi_status`,
  invalid `tags=s.tags` attr access, stale type ignores).
- ~~**Mypy baseline elimination — workers**~~ — DONE (PR #115).
  14 → 0 in `apps/workers/`. CI ratchet at `MAX_MYPY_ERRORS=0`.
  Added `_state_str` / `_state_dict` helpers for type-safe access on
  loosely-typed graph state dicts. Documented latent
  `PostgresSaver.from_conn_string` bug (every worker silently uses
  `MemorySaver` because the `.setup()` call always raises
  `AttributeError` caught by the broad except — needs a follow-up to
  open a real `psycopg.Connection` and pass it to the
  `PostgresSaver(conn=...)` constructor with worker-shutdown plumbing).
- **Mypy baseline elimination — packages** — IN PROGRESS (PRs #117 +
  #118). 129 → 47 in `packages/` (down 82 in 2 stacked PRs). CI
  ratchet to be set at the post-merge count. Surfaced 6 latent silent
  bugs: `InferenceProvider.stream` async-vs-async-generator signature
  mismatch (every streaming caller broke at type check); `agent.py`
  `call_llm` called with wrong arg shape and missing `await` since
  written; 3 SDK examples (`basic_dispatch.py`, `custom_workflow.py`,
  `list_agents.py`) using dict indexing on pydantic models — would
  crash on first real run; `meeting_scheduler.py` loop variable `e`
  shadowing an `except ValueError as e` (Python deletes the except
  name at scope exit). Remaining 47 errors are concentrated in
  langgraph type-system mismatches (`StateGraph.invoke` not yet
  typed), `Client | None` union-attr noise, and one
  `selva_memory.store.Base not valid as type` issue worth a closer
  look — the 5/week rate target should burn down to <20 within a
  couple weeks.
- **Real load test** — target 100 concurrent SwarmTasks; measure DLQ
  depth, worker pool saturation, Redis Stream lag, LLM provider rate
  limits hit. Calibrate `MAX_CONCURRENT_TASKS`, `dispatch_rate_limit`,
  `TIER_DAILY_TASK_LIMIT` from data instead of guesswork.
- **Backup/restore drill** — full restore from backup in staging;
  measure RTO; document RPO; verify off-site/cross-region storage.
  `Makefile` has `db-backup` / `db-restore` targets but no evidence
  of regular testing.
- **SLO definitions + dashboards** — target latency p50/p95/p99 per
  endpoint class; error budget; SLI dashboard. Today there are no SLOs
  documented anywhere.
- **Alert wiring** — DLQ depth, error rate, consent-ledger-grants
  invariant violation, JWKS fetch failures, LLM provider failures,
  Redis pool saturation. Page on-call for criticals.
- **Test coverage to 75%** on critical paths (auth, swarms.dispatch,
  email tools, voice-mode gate, consent ledger, worker org-scoping).
  Security regression tests landed in v2.2.x; broader coverage still
  needed.

### Phase 3 — architectural (next quarter)

- ~~**Audit trail completeness — in-Selva**~~ — DONE. Waves 1+2+3
  (PRs #130, #131, #133) closed all 37 mutation sites identified in
  `docs/AUDIT_TRAIL_GAP_ANALYSIS.md` plus the new `bulk_expire`
  endpoint. **Cross-service replacement** for the manual
  `emit_event_db` discipline is RFC 0019 (PR #140) — Postgres CDC
  (Debezium → Kafka → audit topic). 4-phase 10-week migration plan;
  operator decisions blocking start: Kafka cluster ownership +
  ~$300-800/mo cost approval.
- ~~**Idempotency tokens**~~ — DONE. Helper shipped in PR #127.
  Adopted on 10 mutation endpoints across PRs #141 (Tier 1 — dispatch,
  approve, deny, voice-mode) + #142 (Tier 2 — marketplace.install,
  calendar.connect, maps.create+import, workflows.create+import).
  53 regression tests pin the contract. Org-scoped Redis cache, 24h
  TTL, graceful Redis-down degradation, header-absent no-op
  (caller opt-in). Adoption checklist for new endpoints in
  CLAUDE.md "Patterns Added in v2.3.0".
- **Per-tenant data residency** — RFC 0020 (PR #144) landed.
  Recommended: hybrid Pattern A (dedicated MX-region cluster for
  SAT-bound tenants) + Pattern C (gateway-routed shards for
  everyone else), driven by new `tenant_configs.data_residency_region`
  ENUM column. Phased migration. Implementation blocked on operator
  cluster-provisioning decision.
- **Multi-region failover** — RFC 0021 (PR #144) landed.
  Recommended: active-passive (warm standby, ~30min RTO) for next
  12 months → active-active in Q1 2027 once regional infrastructure
  is mature through quarterly drills. Active-active multi-master
  rejected upfront. Implementation blocked on RFC 0020's cluster
  topology decisions.
- **Compliance audit prep** — SOC 2 Type II is a 6-12 month engagement;
  ISO 27001 similar; LFPDPPP enforcement already active per the v2.2.0
  voice-mode/consent-ledger work.
- **Pricing contract codified** — PARTIAL. Tulana decision doc →
  `infra/pricing/selva-tiers.json` (canonical, schema-validated)
  shipped. Python loader `nexus_api/billing_tiers.py` reads from JSON
  with the same exported names + same fallback semantics (zero
  behaviour change). CI drift gate
  (`tests/test_pricing_codification.py`) asserts loader + JSON +
  CLAUDE.md + emergency fallback all agree. **Remaining**: TS-side
  reader for `apps/office-ui/src/app/bundles/page.tsx` (still has
  hardcoded BUNDLES const for Founder/Operator/Flywheel composite
  bundles); Dhanam catalog API integration (when Dhanam exposes the
  fetch API the JSON becomes the bootstrap fallback only).
- **Real PMF measurement loop** — RFC 0013 widget exists; needs adoption
  tracking, score stability, composite informing tier sunsetting
  decisions automatically.

### Cross-service unknowns (need direct audit of sibling repos)

These cannot be assessed from inside selva-office:

- **Janua** — JWT signing key rotation, refresh token revocation, enterprise
  SSO `org_id` claim mapping production state
- **Dhanam** — actual tier-fetch API; whether it's the source of truth
  selva-office expects, or also fallback-driven
- **Enclii** — rollback success rate, staged rollout discipline, RFC
  0017 digest-pinning enforcement post-deploy
- **PhyndCRM** — own tenant isolation enforcement; whether activities
  from any worker are accepted or properly scoped
- **Karafiel** — Mexican SAT compliance (CFDI, RFC validation) production
  hardening
- **Tulana** — PMF measurement loop ownership and integration

### Honest scorecard (post v2.3.0 remediation)

| Dimension | Today | Target |
|---|---|---|
| App-layer tenant scoping | 95% (was 90%) | 95% |
| Postgres-layer isolation (RLS) | 95% (was 5%) | 95% |
| Outbound governance | 90% | 95% |
| Webhook signature verification | 100% (was 30%) — 15/15 fail-closed | 100% |
| Consent ledger integrity | 95% (was 90%) — per-period key rotation safe | 95% |
| Audit trail breadth (in-Selva) | 100% (was 80%) — 37/37 sites + bulk_expire | 100% |
| Cross-service audit correlation | 20% — RFC 0019 shipped, awaits Kafka | 90% |
| Type safety (Python) | 100% — all 3 trees mypy=0, CI ratchet locked | 100% |
| Type safety (TS) | 80% | 95% |
| Concurrency under load | 50% — scenario shipped, awaits staging run | 85% |
| State persistence across restarts | 95% (was 5%) — PostgresSaver real | 95% |
| Observability — logs | 85% | 95% |
| Observability — traces | 70% (was 10%) — propagation wired, awaits exporter | 90% |
| Observability — alerts | 75% (was 5%) — rules + dashboard ready, awaits OTel data | 90% |
| SLO/SLI definitions | 80% (was 0%) | 80% |
| Idempotency | 90% (was 10%) — helper + 10 endpoints adopted | 90% |
| Load test scenarios | 80% (was 30%) | 90% |
| Backups + DR | unknown — runbook in RFC 0021 | 90% |
| Deployment pipeline | 70% | 90% |
| Pricing source-of-truth | 75% (was 30%) — JSON canonical + drift gate | 85% |
| Secret rotation | 100% (was 0%) — script + policy + per-period keys | 100% |
| Architecture RFCs landed | 5 of 5 (#0017, #0018, #0019, #0020, #0021) | 5 |
| Schema coherence cross-language | 40% | 85% |
| Frontend code health | 60% | 85% |
| A11y (WCAG 2.1 AA) | 65% | 90% |

**Weighted overall: ~88-92% of "fully production stable +
data-truthful"** as of 2026-05-04 (v2.3.0 sprint). Staging bootstrap
(PP.4), doc-truth remediation, and DNS/tunnel fix landed 2026-05-30 —
see [CHANGELOG.md](CHANGELOG.md) and [docs/PP_4_STAGING_AUDIT.md](docs/PP_4_STAGING_AUDIT.md).

**North star gap (~45-58% → 100%):** See
[docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md).
Phase 2 campaign API + UI shipped (#179); remaining gap is operator proof
(Dhanam webhooks, k6, OTel/Sentry) and Phases 3–5.

Major movements 2026-05-04 session:
- Workers + packages mypy: 14 → 0 + 129 → 0 (2 of 2 trees pinned at 0)
- PostgresSaver silent state-loss bug closed (durable across restarts)
- 5 RLS Phase 1.5 break sites migrated to ``tenant_session()`` helper
- 8+ latent silent-failure bugs surfaced and fixed by mypy + reviews
- Stripe webhook real handlers (5 events + migration 0027)
- 15/15 webhook handlers fail-closed
- Audit-trail completeness 16 → 38 emit sites (waves 1+2; wave 3 in flight)
- Idempotency-Key dependency + 13 tests
- 100-concurrent-SwarmTasks load scenario + runbook
- SLO definitions doc + per-PR adoption checklist
- CI test-py + wire-types-drift gates restored to green
- Stale `/api/v1/swarms/tasks/reap-stale` tenant-scoping bug fixed

---

## Historical (pre-v2.2.x)

> Sections below capture prior milestones, sprint history, ecosystem
> integration map, and the older Factory-as-a-Product / Enterprise
> Autonomy roadmaps. Forward-looking sequencing lives in the
> "Roadmap to Production-Truthful" section above.

## Completed Milestones

### Q3/Q4: Autonomous Cleanroom Protocol ✅
LangGraph execution engine, Playwright browser tooling, durable task queue,
airgap handoff, Enclii deployment integration, QA Oracle sandbox.

### Q1: Hive Mind & Continuous Learning ✅
Autonomous skill generation, FTS5 edge memory, serverless hibernation,
MCP capabilities, dialectic profiling, 18-channel gateway.

### Q2: Hermes Gap Remediation ✅
Waves 1-4: skill refiner, memory compactor, cron scheduler, browser/vision,
HITL approval gate, plugin architecture, prompt caching, context compression,
session checkpoints, SOUL.md, 23 new tools, skills hub.

### Competitive Dominance Waves 1-4 (v0.6.0–v0.9.0) ✅
Screen sharing polish, iterative skill refinement, PWA, voice STT (Whisper),
LiveKit SFU scaling, tool expansion (→54), A2A protocol, mobile UX polish,
competitive benchmark documentation.

### Solarpunk Visual Overhaul Phases 1-4 (v1.0.0–v1.2.0) ✅
Warm earth palette, 79 FF6-quality tiles, 12-pose walk cycles, solarpunk UI
tokens + particles, Living Office biome map, atmospheric lighting, companions,
emotes, animated tiles, agent idle animations.

### Codebase Remediation (v0.5.1–v1.2.1) ✅
K8s env fix, Alembic migration chain, SSRF protection, bare exception logging,
auth exports, skills package fix, Colyseus state sync, brand correction
(MADFAM ecosystem / Selva product), zero ruff errors, hardcoded localhost fix.

---

## Selva Brand Deployment Checklist

- `[x]` Product domains: `api.selva.town`, `ws.selva.town`, `admin.selva.town`, `app.selva.town`
- `[x]` MADFAM ecosystem preserved: `auth.madfam.io`, `crm.madfam.io`, `status.madfam.io`, `npm.madfam.io`
- `[x]` Redirect config: `selvatown.com` → `selva.town` (301)
- `[x]` DNS records provisioned in Cloudflare (all zones)
- `[x]` Cloudflare Tunnel routes configured
- `[x]` Email routing: `*@selva.town` → `admin@madfam.io`
- `[x]` Docker images built + pushed to `ghcr.io/madfam-org`
- `[x]` K8s secrets (8 keys) + configmap (org-config) deployed
- `[x]` Alembic migrations applied in production
- `[x]` MADFAM org seeded (4 nodes, 10 named agents)
- `[ ]` `selva.town/terms` and `selva.town/privacy` pages
- `[ ]` Working unsubscribe endpoint at `madfam.io/unsubscribe`

---

## Factory-as-a-Product Protocol Roadmap

> **Goal**: End-to-end phygital pipeline where a customer's digital design
> becomes a quoted, manufactured, shipped, and invoiced physical product —
> entirely orchestrated by Selva agents.

### Phase F1: Autonomous Revenue Loop — Program Phase 1 🔄

> **Program mapping:** [AUTONOMOUS_OPERATIONS_PROGRAM.md § Phase 1](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-1--closed-revenue-loop-3-4-weeks)

The CRM-driven email loop is deployed and security-hardened. **Code complete**
(2026-04-16); **not yet live** for revenue attribution. Waiting on Phase 0
(Stripe map, OTel) + provider credits + `FEATURE_STRIPE_MXN_LIVE`.

```
HeartbeatService (*/30 cron)
  → CRM Scraper → Hot Lead Detection
    → Auto-Dispatch (dedup, 10/tick cap, HITL gate)
      → LLM Drafts Email (via inference proxy)
        → Resend Sends (madfam.io verified, CAN-SPAM compliant)
          → Dhanam Checkout CTA (Stripe MX, 6 products, 15 prices)
            → Payment → Subscription Activation
```

Status: **Program Phase 1** — blocked on operator wiring (OPERATOR_BACKLOG
items 1–3) + Anthropic credits + Stripe live mode verification.

### Phase F2: Compliance Wedge (GTM Wave 1) — Program Phases 4–5

Lead with Karafiel compliance for Mexican SMBs:
- `[x]` CFDI 4.0 tools (generate, stamp, status, blacklist check)
- `[x]` RFC validation
- `[x]` Billing graph (6-node monthly close)
- `[ ]` Karafiel public pricing page ($499 MXN/mo)
- `[ ]` 10+ paying customers on Karafiel compliance
- `[ ]` Referral flywheel active (PhyndCRM funnel → Dhanam rewards)

### Phase F3: Fabrication Bundle (GTM Wave 2) — Program Phase 3

> **Program mapping:** [AUTONOMOUS_OPERATIONS_PROGRAM.md § Phase 3](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-3--multi-product-phygital-orchestration-6-8-weeks)

Bundle Cotiza + Yantra4D + PravaraMES for digital fabrication shops:
- `[x]` Cotiza↔Yantra4D bidirectional webhooks
- `[x]` Cotiza↔PravaraMES HMAC-signed order webhooks
- `[x]` PravaraMES↔Dhanam usage billing
- `[ ]` **Phygital workflow graph** (`phygital.py`): design → quote → approve → manufacture → ship → invoice
  - Yantra4D: customer uploads parametric design, Selva renders + generates BOM
  - Cotiza: auto-quotes based on BOM + ForgeSight market pricing
  - Customer approval (HITL gate in browser at app.selva.town)
  - PravaraMES: creates work order, tracks production
  - Dhanam: generates invoice, CFDI stamp via Karafiel
  - Logistics: shipment tracking (Estafeta/FedEx MX integration — future)
- `[ ]` End-to-end demo: parametric design → physical product delivered

### Phase F4: Intelligence APIs (GTM Wave 3)

Expose Fortuna + Tezca + Forgesight as paid APIs:
- `[x]` Inference centralized through Selva proxy
- `[x]` API key system via Janua + credit metering via Dhanam
- `[ ]` Fortuna public API (problem intelligence, market sensing)
- `[ ]` Tezca public API (legal search, 30K+ Mexican laws)
- `[ ]` Forgesight public API (fabrication pricing intelligence)

### Phase F5: Full Platform Launch (GTM Wave 4-5)

Selva seats at $149-499/mo as the autonomous AI workforce:
- `[ ]` Proven unit economics (LTV > CAC)
- `[ ]` Multi-tenant self-provisioning
- `[ ]` Per-tenant compute budgets wired to Dhanam subscriptions
- `[ ]` White-label capability
- `[ ]` 3D Voxel View (React Three Fiber + MagicaVoxel)
- `[ ]` $500K MRR target at 24 months

---

## Enterprise Autonomy Roadmap

### Phase E1: Multi-Tenant Enterprise Hardening

**Goal**: Any Mexican business can self-provision a Selva org and start running autonomous operations.

- `[x]` **Tenant provisioning API** (Sprint 7): `POST /api/v1/tenants/`, TenantConfig model, migration 0015, RFC validation via Karafiel
- `[x]` **Department templates** (Sprint 7): Auto-create 6 Mexican departments (Dirección General, Administración, Contabilidad, Ventas, Operaciones, Legal)
- `[x]` **Daily task limits** (Sprint 7): Per-tenant enforcement (429) in swarms dispatch
- `[ ]` **Per-tenant compute budgets**: Wire Dhanam subscription tier → quota enforcement
- `[ ]` **Tenant data isolation audit**: Verify RLS on all 16 tables, Redis key prefixing, Colyseus room isolation
- `[ ]` **Enterprise SSO**: SAML/OIDC via Janua per-tenant connections
- `[ ]` **White-label capability**: Per-tenant branding (logo, colors, custom domain)

**MADFAM Ecosystem Integration**:
| Repo | Role | Integration |
|------|------|-------------|
| `janua/` | Authentication | SSO, OIDC, enterprise connections, guest access |
| `dhanam/` | Billing | Per-tenant subscription, compute token ledger, usage metering |
| `enclii/` | Deployment | Tenant-isolated worker pod provisioning, scale-to-zero |
| `phynd-crm/` | CRM | Per-tenant customer data, pipeline, activity feed |

### Phase E2: Mexican Regulatory Compliance

**Goal**: Agents autonomously handle SAT obligations, labor law compliance, and data privacy.

#### SAT / CFDI 4.0 (Electronic Invoicing)
- `[x]` **CFDI tools via Karafiel** (Sprint 1): CFDIGenerate, CFDIStamp, CFDIStatus, BlacklistCheck — all delegating to Karafiel's DRF API
- `[x]` **Billing graph** (Sprint 1): 6-node workflow (fetch → validate RFCs → blacklist → generate → stamp → notify) with conditional edges
- `[x]` **RFC validation** (Sprint 1): RFCValidationTool via KarafielAdapter + regex format check in tenants router
- `[x]` **WhatsApp invoice delivery** (Sprint 2): factura_enviada template via Meta Business API
- `[x]` **Invoices API**: POST /generate + GET /{uuid}/status
- `[ ]` **Constancia de Situación Fiscal** lookup via Karafiel SAT portal agent
- `[ ]` **Complemento de Pagos**: Partial payment CFDI complement via Karafiel

**Integration**: All compliance via `karafiel/` (SAT, CFDI, fiscal modules)

#### Labor Law (Ley Federal del Trabajo)
- `[ ]` **Nómina calculation engine**: ISR retention tables (SAT annual update), IMSS cuotas, INFONAVIT, fondo de ahorro
- `[ ]` **IMSS automation**: Alta, baja, modificación salarial via IDSE/SUA integration
- `[ ]` **Vacation tracking**: 12+ days first year (2023 reform), progressive scale, prima vacacional (25%)
- `[ ]` **Aguinaldo calculation**: 15 days minimum by Dec 20, pro-rata for partial year
- `[ ]` **PTU distribution**: 10% of fiscal profit, 50/50 split (days worked / salary proportion)
- `[ ]` **NOM-035 compliance**: Psychosocial risk surveys, STPS report generation

#### Data Privacy (LFPDPPP)
- `[ ]` **PII classification tagging** on all agent-processed documents
- `[ ]` **Right-to-deletion workflow**: Agent searches + purges PII across artifacts, memory, transcripts
- `[ ]` **Privacy notice generator**: Per-tenant aviso de privacidad from template
- `[ ]` **Cross-border data transfer controls**: Flag when data leaves Mexican jurisdiction

### Phase E3: Department-Specific Autonomous Workflows

**Goal**: Pre-built graph templates that agents execute end-to-end for each department.

#### Contabilidad (Accounting) ✅ Sprint 4
- `[x]` **Accounting graph**: 5-node monthly close (fetch → reconcile → compute taxes → prepare declaration → HITL review)
- `[x]` **DhanamAdapter**: list_transactions, get_bank_statements (Belvo), get_payment_summary (Stripe MX/Conekta/OXXO/SPEI), get_pos_transactions, economic indicators (exchange rate, TIIE, inflation, UMA)
- `[x]` **Tax tools**: ISRCalculator, IVACalculator, BankReconciliation, DeclarationPrep, PaymentSummary — all via Karafiel/Dhanam
- `[x]` **Tax compliance skill**: SKILL.md + SKILL.es-MX.md
- `[ ]` CONTPAQi / Aspel adapter for ERP export

#### Ventas (Sales) ✅ Sprint 5
- `[x]` **Sales graph**: 7-node pipeline (qualify → cotización → approval → send → pedido → billing → cobranza)
- `[x]` **WhatsApp Business templates** (Sprint 2): factura_enviada, recordatorio_pago, confirmacion_pedido, cotizacion_lista
- `[x]` **PhyndCRM integration**: lead scoring, pipeline management, activity logging
- `[x]` **Sales pipeline skill**: SKILL.md + SKILL.es-MX.md
- `[ ]` Pipeline analytics dashboard in office UI

#### Recursos Humanos (HR)
- `[ ]` Onboarding workflow: IMSS alta, contract generation, NDA, handbook delivery
- `[ ]` Offboarding: IMSS baja, finiquito/liquidación calculation, constancia laboral
- `[ ]` Performance review cycle with 360° feedback
- `[ ]` Training tracking for STPS compliance

#### Legal ✅ Sprint 5
- `[x]` **Legal tools**: ContractGenerate (→Karafiel CLM), REPSECheck (→Karafiel), LawSearch (→Tezca), ComplianceCheck (→Tezca)
- `[x]` **TezcaAdapter**: search_laws, get_article, check_compliance
- `[x]` **Legal compliance skill**: SKILL.md + SKILL.es-MX.md
- `[ ]` Poder notarial tracking and renewal alerts
- `[ ]` **MADFAM integration**: `legal-ops/` for contract lifecycle management

#### Operaciones (Operations)
- `[ ]` Supply chain: pedimento document automation for customs
- `[ ]` Inventory management with IMMEX/PITEX regime awareness
- `[ ]` Logistics: Mexican carrier integration (Estafeta, FedEx MX, DHL, Paquetexpress)
- `[ ]` **MADFAM integration**: `pravara-mes/` for manufacturing execution, `digifab-quoting/` for fabrication quotes, `routecraft/` for logistics optimization

### Phase E4: Mexican Market Intelligence Layer

**Goal**: Agents proactively monitor regulatory, economic, and market changes.

- `[ ]` **SAT monitor agent**: RFC status, tax obligation alerts, constancia updates
- `[x]` **DOF agent** (Sprint 6): DOFMonitorTool via CrawlerAdapter → madfam-crawler
- `[ ]` **INEGI data integration**: GDP, employment, industry-specific indicators
- `[x]` **Economic indicators via Dhanam** (Sprint 6): ExchangeRate (USD/MXN), TIIE, Inflation, UMA — all via DhanamAdapter
- `[x]` **UMA/UMI tracker** (Sprint 6): UMATrackerTool via DhanamAdapter
- `[x]` **Intelligence graph** (Sprint 6): 4-node daily briefing (scan DOF → economic data → LLM briefing → notify team)
- `[x]` **Market intelligence skill**: SKILL.md + SKILL.es-MX.md
- `[ ]` **SIEM compliance**: Annual registration automation
- `[ ]` **Profeco monitor**: Consumer protection regulation changes
- `[ ]` **MADFAM integration**: `social-sentiment-monitor/` for brand monitoring, `fortuna/` for market problem intelligence

### Phase E5: Localization & Cultural Adaptation

**Goal**: Every agent interaction feels native to Mexican business culture.

- `[x]` **Full Spanish (MX) language support** (Sprint 3): 15 SKILL.es-MX.md files, locale-aware system prompts (plan/implement/review), graph prompt variants (project, crm, billing, coding, research), SkillRegistry locale parameter
- `[x]` **Timezone/currency/locale** (Sprint 7): TenantConfig with defaults (America/Mexico_City, MXN, es-MX)
- `[ ]` **Mexican business calendar**: Art. 74 LFT holidays, puentes, Semana Santa, Buen Fin, CFDI deadlines
- `[ ]` **Number/date formatting**: DD/MM/YYYY, comma thousands, period decimal
- `[ ]` **MADFAM integration**: `madfam-site/` for Mexican-localized marketing pages

### Phase E6: Enterprise Architecture Scaling

**Goal**: Support 100+ concurrent tenant organizations with full data sovereignty.

- `[ ]` **Multi-region deployment**: Primary in Mexico-adjacent region (GCP `us-south1` / AWS `us-east-1`), latency <30ms from CDMX
- `[ ]` **Data residency option**: All-Mexico hosting for government contracts and LFPDPPP compliance
- `[ ]` **Horizontal scaling**: Auto-scale workers per tenant load via Enclii (`enclii/`)
- `[ ]` **API-first architecture**: Every agent capability exposed via REST + A2A for integration with Mexican ERPs (SAP, Oracle, CONTPAQi, Aspel, Microsip)
- `[ ]` **Offline-capable PWA**: Critical for businesses in areas with intermittent connectivity
- `[ ]` **Audit trail**: Complete event log per tenant for regulatory compliance (SAT audits, STPS inspections)
- `[ ]` **MADFAM integration**: `internal-devops/` for infrastructure automation, `enclii/` for deployment orchestration

---

## Full MADFAM Ecosystem Integration Map

```
MADFAM Ecosystem (Innovaciones MADFAM SAS de CV)
│
├── 🏢 Selva Office (selva-office/) — THIS PRODUCT
│   ├── selva.town — Virtual office + AI agent swarm
│   ├── 268 built-in tools, 12 graphs, 6 adapters, 18 gateways, A2A protocol
│   └── Solarpunk UI, PWA, LiveKit SFU, es-MX locale, multi-tenant
│
├── 🔐 Janua (janua/) — Authentication & SSO
│   ├── auth.madfam.io
│   ├── OIDC/SAML, enterprise connections, guest access
│   └── → Selva uses for all user auth + tenant isolation
│
├── 💰 Dhanam (dhanam/) — Billing & Subscriptions
│   ├── dhan.am
│   ├── Compute token ledger, subscription tiers, webhooks
│   └── → Selva uses for per-tenant metering + quotas
│
├── 🚀 Enclii (enclii/) — Deployment & Infrastructure
│   ├── enclii.dev
│   ├── Container orchestration, scale-to-zero, webhooks
│   └── → Selva uses for worker pod provisioning + deployment graph
│
├── 📊 PhyndCRM (phynd-crm/) — Customer Relationship Management
│   ├── crm.madfam.io
│   ├── Contacts, pipeline, activities, billing profiles
│   └── → Selva uses for CRM graph, lead data, customer context
│
├── ⚖️ Tezca (tezca/) — Legal Intelligence
│   ├── tezca.mx
│   └── → Selva E3: contract analysis, regulatory monitoring
│
├── 🔮 Fortuna (fortuna/) — Problem Intelligence
│   ├── fortuna.tube
│   └── → Selva E4: market problem detection, opportunity scoring
│
├── 🏭 Pravara MES (pravara-mes/) — Manufacturing Execution
│   └── → Selva E3: production scheduling, quality tracking
│
├── 🎨 Yantra4D (yantra4d/) — 3D Design & Digital Twins
│   ├── yantra4d.com
│   └── → Selva E3: product visualization, facility planning
│
├── 🧮 Coforma Studio (coforma-studio/) — Fabrication Quoting
│   ├── cotiza.studio
│   └── → Selva E3: manufacturing cost estimation
│
├── 🎰 CEQ (ceq/) — Creative AI Engine
│   ├── ceq.lol
│   └── → Selva E3: content generation, brand creative
│
├── 📡 Madfam Crawler (madfam-crawler/) — Web Intelligence
│   └── → Selva E4: DOF monitoring, competitor tracking
│
├── 📈 Social Sentiment Monitor (social-sentiment-monitor/)
│   └── → Selva E4: brand monitoring, market sentiment
│
├── 🧾 Factlas (factlas/) — Invoice/CFDI Services
│   └── → Selva E2: CFDI 4.0 stamping, SAT integration
│
├── 📐 Geom Core (geom-core/) — Geometry Engine
│   └── → Yantra4D dependency, spatial calculations
│
├── 🌿 Solarpunk Foundry (solarpunk-foundry/) — Design System
│   └── → Selva: solarpunk UI tokens, component library
│
├── 🎴 Stratum TCG (stratum-tcg/) — Card Game
├── 🌙 Nuit One (nuit-one/) — Night Operations
├── 🏗️ Forj (forj/) — Build Tools
├── 🔍 Forgesight (forgesight/) — Code Analysis
├── 📜 Bloom Scroll (bloom-scroll/) — Document Platform
├── 🧪 Sim4D (sim4d/) — Simulation Engine
├── 🏪 Tablaco (tablaco/) — Marketplace
├── 🛤️ Routecraft (routecraft/) — Logistics
├── 🎯 Zavlo (zavlo/) — Task Management
├── 🔧 Blueprint Harvester (blueprint-harvester/) — Schema Extraction
├── 📧 Proton Bridge Pipeline (proton-bridge-pipeline/) — Email Processing
├── 🏠 Karafiel (karafiel/) — Property Management
├── 💎 Avala (avala/) — Asset Valuation
├── 🖥️ Server Auction Tracker (server-auction-tracker/) — Hardware
├── 🎮 Turnbased Engine (turnbased-engine/) — Game Engine
├── 🌐 Madfam Site (madfam-site/) — Corporate Website
├── 🔒 Primavera3D (primavera3d/) — 3D Security
├── 📋 Rondelio (rondelio/) — Inspections
├── 🛡️ Internal DevOps (internal-devops/) — Infrastructure
└── 📦 Autoswarm Sandbox (autoswarm-sandbox/) — Agent Testing
```

---

## Autonomous Revenue Loop (v2.1.0) — 2026-04-16 ✅ Code Complete

### Infrastructure Deployed
- `[x]` HeartbeatService cron (`*/30 * * * *`) with CRM scraper + auto-dispatch
- `[x]` PlaybookGuard with conditional approval bypass + financial circuit breaker ($50/day)
- `[x]` CRM graph: fetch_context → draft_communication → approval_gate → send (Resend + PhyndCRM log)
- `[x]` Resend Pro transactional ($20/mo, 50K emails, 10 domains). madfam.io verified
- `[x]` MADFAM branded HTML email template (table-based, Outlook/Gmail/Apple Mail compatible)
- `[x]` Service consumption tracking (email sends → event stream)
- `[x]` Email delivery skill definition (`packages/skills/skill-definitions/email-delivery/SKILL.md`)
- `[x]` Security hardened: dev-bypass rejected in production, proper SSO via Janua PKCE
- `[x]` Responsive UI: Phaser RESIZE mode, mobile HUD, chat compaction
- `[x]` Player spawn fix: TMJ map spawn points (not hardcoded wall tile)

### Inference Centralization
- `[x]` OpenAI-compatible proxy at `/v1/chat/completions` + `/v1/embeddings` (`inference_proxy.py`)
- `[x]` Shared `build_router_from_env()` factory (`packages/inference/madfam_inference/factory.py`)
- `[x]` Org-config ConfigMap deployed to K8s, mounted at `/etc/autoswarm/org-config.yaml`
- `[x]` ServiceConfig model for tracking external accounts (Resend, Anthropic, DeepInfra, Stripe, etc.)
- `[x]` PhyndCRM, Fortuna, Yantra4D secrets patched for Selva inference routing
- `[x]` 196 inference tests passing (org_config + router + factory + worker wiring)

### Blocking First Revenue
- `[ ]` **Anthropic API credits** — $0 balance blocks all LLM inference. Add $20 at console.anthropic.com
- `[ ]` **Stripe live mode** — Verify `sk_live_` prefix (not `sk_test_`)
- `[ ]` Resend domain verification (9 pending — DNS records added, click "Verify" in dashboard)
- `[ ]` DeepInfra API key (optional — 13x cost reduction on volume tasks)
- `[ ]` PhyndCRM webhook registration (CRM → Selva event flow)

---

## Immediate Next Sprint (Priority Order)

1. `[ ]` **Add Anthropic credits** — Unblocks entire autonomous loop + all ecosystem AI features
2. `[ ]` **Verify Stripe live mode** — Confirm real payments can flow
3. `[ ]` **Verify Resend domains** — Expand branded email across 9 ecosystem services
4. `[ ]` **First autonomous sale** — HeartbeatService picks up lead → drafts email → sends → checkout CTA → payment
5. `[ ]` **DeepInfra API key** — 13x cost reduction ($0.23 vs $3 per 1M tokens)
6. `[ ]` **3D Voxel View** — React Three Fiber + MagicaVoxel (see `ROADMAP_3D_VOXEL.md`)

---

## Verified Tablaco Quote Flow (Selva -> Yantra4D -> Cotiza -> ForgeSight)

Selva agents must only return client-facing fabrication quotes when the downstream services prove the quote is tenant-scoped, project-specific, and market verified.

### Priority Implementation Items

1. `[ ]` **Agent identity wiring** — Provide Selva workers with the Janua/Yantra4D and Cotiza tenant credentials needed to call the production quote path without bypassing access control.
2. `[ ]` **Strict quote tool contract** — Default client-ready quote generation to `require_market_verified=true`.
3. `[ ]` **Verification guard** — Refuse to return a successful client quote unless Yantra4D/Cotiza/ForgeSight response data includes `market_verified=true`.
4. `[ ]` **Tablaco E2E test** — Exercise `project_slug=tablaco`, `mode=unit`, PLA/FDM, MXN, and a safe test client.
5. `[ ]` **Dependency hygiene** — Ensure local and CI environments install the Selva tool dependencies required for quote-tool execution.
6. `[ ]` **Runbook** — Document the quote flow, expected failures, credentials, and Enclii verification commands.

### Acceptance Gate

The Selva quote tool returns success for Tablaco only when the final response contains a verified ForgeSight market context. Otherwise, Selva must return a non-client-ready failure with the exact blocker.

---

## Production Readiness Checklist

- `[x]` Zero Python lint errors (ruff)
- `[x]` Zero TypeScript type errors
- `[x]` 817+ TS tests passing
- `[x]` 252+ Python tests passing (196 inference alone)
- `[x]` 7/7 build tasks successful
- `[x]` 139 API routes loaded
- `[x]` Docker compose valid (8 services)
- `[x]` All hardcoded localhost → env vars
- `[x]` SSRF protection on all webhook handlers
- `[x]` Zero bare except:pass
- `[x]` Brand architecture correct (MADFAM ecosystem / Selva product)
- `[x]` PWA installable
- `[x]` Solarpunk visual overhaul complete
- `[x]` Org-config ConfigMap deployed to K8s
- `[x]` Inference proxy live (`/v1/chat/completions` + `/v1/embeddings`)
- `[x]` Ecosystem inference centralized (Fortuna, Yantra4D, PhyndCRM → Selva proxy)
- `[x]` Service resource registry (8 external accounts tracked)
- `[x]` Email delivery verified (Resend Pro, madfam.io domain)
- `[x]` 6 selva pods healthy (nexus-api, workers, gateway, colyseus, office-ui, admin)
- `[x]` ArgoCD synced to latest commit
- `[x]` Dev-bypass rejected in production auth
- `[ ]` Anthropic API credit balance > $0
- `[ ]` Stripe MX in live mode (sk_live_)
- `[ ]` Gateway secrets injection (DingTalk, Feishu, etc.)
- `[ ]` Docker socket sandboxing for worker pods
