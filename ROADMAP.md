# Selva Office — Product Roadmap

> **Selva** is the autonomous virtual office product by **Innovaciones MADFAM SAS de CV**.
> It runs at `selva.town` and integrates with the full MADFAM ecosystem.
> _The legacy "AutoSwarm Office" name is retained only inside historical migration
> identifiers and a few infra namespaces. The product, repo, and brand are Selva._

---

## Current Status: v2.2.0 — Outbound Voice Mode + Consent Ledger ✅

> Supersedes the v2.0.0 "Enterprise Mexican Market MVP" milestone. v2.1.1 added
> autonomous-pipeline security hardening; v2.2.0 added the three-mode voice/consent
> system + append-only consent ledger.

| Metric | Value | Source |
|--------|-------|--------|
| Built-in tools | 240 (`selva_tools/builtins/`) | `grep -rE "^class [A-Z][A-Za-z]+Tool" packages/tools/src/selva_tools/builtins/` |
| Workflow graphs | 12 (accounting, billing, coding, crm, deployment, intelligence, meeting, operations, project, puppeteer, research, sales) | `apps/workers/selva_workers/graphs/*.py` |
| Ecosystem adapters | 6 (Karafiel, Dhanam, PhyneCRM, Tezca, Crawler, A2A) | `packages/tools/src/selva_tools/adapters/` |
| Skills (en + es-MX) | 17 (15 tenant + meta) | `packages/skills/skill-definitions/` |
| Alembic migrations | 25 (0000–0018 + Wave 2 chain) | `apps/nexus-api/alembic/versions/*.py` |
| Test files | 794 (pytest + vitest + playwright) | `find apps packages tests -name "test_*.py" -o -name "*.test.ts" -o -name "*.spec.ts"` |
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
  `FEATURE_STRIPE_MXN_LIVE=true` in production. Per-event handlers
  TBD per Phase 2 as each event type becomes operationally relevant.
- **Production secrets provisioned** — `WORKER_API_TOKEN`,
  `CONSENT_LEDGER_SIGNING_SECRET`, `COLYSEUS_SERVICE_TOKEN` all need
  strong values in staging + prod. Settings validators now refuse
  weak / dev defaults in production environment.
- **OTel exporter actually wired** — `OTEL_EXPORTER_OTLP_ENDPOINT` is
  read but no-op when unset. Pick a backend (Honeycomb / Tempo /
  Datadog), wire the env var, get traces flowing for at least one
  request path end-to-end.
- **Sentry DSN per service** — `init_sentry()` exists but DSNs are
  missing from `.env.example`; verify it's actually catching errors.
  Add source-map upload for office-ui in CI.

### Phase 1.5 — RLS tightening (after 1-2 weeks of production observation)

- **Audit every code path that runs without `org_id_var` set** — the
  Phase 1 RLS policies use a permissive escape hatch (NULL/empty
  session org → policy permits) so Alembic / healthchecks / demo /
  unauthenticated paths keep working. After observing production
  query patterns, enumerate every legitimate "no tenant context"
  path and either: (a) set an explicit context (e.g. "platform" for
  MADFAM-internal queries), or (b) document each one.
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

- **Tenant onboarding UI for outbound identity** — `outbound_user_email`,
  `outbound_user_name`, `outbound_agent_slug` as first-class
  `tenant_configs` columns + Alembic migration + onboarding step + UI.
  Until this exists, the email lockdown (commit f35f1b1) reads from
  `tenant_configs.brand_name` / `razon_social` / `tenant_identities`
  joined on `canonical_id` as best-effort fallbacks; tenants who haven't
  manually populated `tenant_identities` get email refusals with
  "Tenant outbound identity not configured."
- **Schema codegen TS↔Python** — 29 Python ORM models, ~7 TypeScript
  shared-types interfaces. Frontend hooks call uncovered endpoints with
  `Record<string, unknown>` ad-hoc shapes. Pipeline: `datamodel-code-generator`
  generates JSON Schema → `json-schema-to-typescript` emits TS. CI fails
  on drift.
- **AUDIENCE_FILTER_ENABLED=true** — currently shadow-mode (default
  `false`). After 24-48h observation in production confirms the
  shadow-block log is empty, flip the gate so platform-only tools
  actually refuse tenant invocations.
- **Mypy baseline elimination** — 144 errors in nexus-api, ~20 in
  workers. Ratchet via CI: no new errors allowed; fix 10/week. Most are
  `dict[str, Any]` overuse and missing return types in routers.
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

- **Audit trail completeness** — Postgres CDC (Debezium → Kafka → audit
  topic) or systematic `emit_event` review on every state change. Today
  many writes (tenant_configs updates, marketplace publish/install,
  agent CRUD) don't emit a TaskEvent.
- **Idempotency tokens** — every mutation endpoint accepts an
  idempotency key; replay-safe. Today retry semantics depend on each
  caller getting it right.
- **Per-tenant data residency** — Mexican LFPDPPP enforcement now
  active; SAT submissions need data in-country. Likely needs
  tenant-scoped DB per region OR partitioning by tenant region.
- **Multi-region failover** — read replicas; automatic failover; tested.
- **Compliance audit prep** — SOC 2 Type II is a 6-12 month engagement;
  ISO 27001 similar; LFPDPPP enforcement already active per the v2.2.0
  voice-mode/consent-ledger work.
- **Pricing contract codified** — Tulana decision doc → JSON →
  Dhanam catalog API → bundle page UI all read from one place; CI
  fails if they drift. Current state: CLAUDE.md cites a non-existent
  `scripts/seed-mvp.py` for pricing; bundle prices live in
  `apps/office-ui/src/app/bundles/page.tsx`; Dhanam tier-fetch path
  is hardcoded fallback dict in `nexus_api/billing_tiers.py`.
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
- **PhyneCRM** — own tenant isolation enforcement; whether activities
  from any worker are accepted or properly scoped
- **Karafiel** — Mexican SAT compliance (CFDI, RFC validation) production
  hardening
- **Tulana** — PMF measurement loop ownership and integration

### Honest scorecard (post v2.2.x remediation)

| Dimension | Today | Target |
|---|---|---|
| App-layer tenant scoping | 90% | 95% |
| Postgres-layer isolation (RLS) | 5% | 90% |
| Outbound governance | 90% | 95% |
| Webhook signature verification | 30% | 95% |
| Consent ledger integrity | 90% | 95% |
| Audit trail breadth | 60% | 90% |
| Type safety (Python) | 60% | 90% |
| Type safety (TS) | 80% | 95% |
| Concurrency under load | 50% | 85% |
| Observability — logs | 85% | 95% |
| Observability — traces | 10% | 80% |
| Observability — alerts | 5% | 90% |
| SLO/SLI definitions | 0% | 80% |
| Backups + DR | unknown | 90% |
| Deployment pipeline | 70% | 90% |
| Pricing source-of-truth | 30% | 85% |
| Schema coherence cross-language | 40% | 85% |
| Frontend code health | 60% | 85% |
| A11y (WCAG 2.1 AA) | 65% | 90% |

Weighted overall: roughly 45-55% of "fully production stable +
data-truthful." Was 25-30% before the v2.2.x remediation.

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

### Phase F1: Autonomous Revenue Loop ✅ Code Complete (2026-04-16)

The CRM-driven email loop is deployed and security-hardened. Waiting on
Anthropic credits and Stripe live mode confirmation.

```
HeartbeatService (*/30 cron)
  → CRM Scraper → Hot Lead Detection
    → Auto-Dispatch (dedup, 10/tick cap, HITL gate)
      → LLM Drafts Email (via inference proxy)
        → Resend Sends (madfam.io verified, CAN-SPAM compliant)
          → Dhanam Checkout CTA (Stripe MX, 6 products, 15 prices)
            → Payment → Subscription Activation
```

Status: **Blocked on $20 Anthropic credits + Stripe live mode verification.**

### Phase F2: Compliance Wedge (GTM Wave 1)

Lead with Karafiel compliance for Mexican SMBs:
- `[x]` CFDI 4.0 tools (generate, stamp, status, blacklist check)
- `[x]` RFC validation
- `[x]` Billing graph (6-node monthly close)
- `[ ]` Karafiel public pricing page ($499 MXN/mo)
- `[ ]` 10+ paying customers on Karafiel compliance
- `[ ]` Referral flywheel active (PhyneCRM funnel → Dhanam rewards)

### Phase F3: Fabrication Bundle (GTM Wave 2)

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
| `phyne-crm/` | CRM | Per-tenant customer data, pipeline, activity feed |

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
- `[x]` **PhyneCRM integration**: lead scoring, pipeline management, activity logging
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
│   ├── 240 built-in tools, 12 graphs, 6 adapters, 18 gateways, A2A protocol
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
├── 📊 PhyneCRM (phyne-crm/) — Customer Relationship Management
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
- `[x]` CRM graph: fetch_context → draft_communication → approval_gate → send (Resend + PhyneCRM log)
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
- `[x]` PhyneCRM, Fortuna, Yantra4D secrets patched for Selva inference routing
- `[x]` 196 inference tests passing (org_config + router + factory + worker wiring)

### Blocking First Revenue
- `[ ]` **Anthropic API credits** — $0 balance blocks all LLM inference. Add $20 at console.anthropic.com
- `[ ]` **Stripe live mode** — Verify `sk_live_` prefix (not `sk_test_`)
- `[ ]` Resend domain verification (9 pending — DNS records added, click "Verify" in dashboard)
- `[ ]` DeepInfra API key (optional — 13x cost reduction on volume tasks)
- `[ ]` PhyneCRM webhook registration (CRM → Selva event flow)

---

## Immediate Next Sprint (Priority Order)

1. `[ ]` **Add Anthropic credits** — Unblocks entire autonomous loop + all ecosystem AI features
2. `[ ]` **Verify Stripe live mode** — Confirm real payments can flow
3. `[ ]` **Verify Resend domains** — Expand branded email across 9 ecosystem services
4. `[ ]` **First autonomous sale** — HeartbeatService picks up lead → drafts email → sends → checkout CTA → payment
5. `[ ]` **DeepInfra API key** — 13x cost reduction ($0.23 vs $3 per 1M tokens)
6. `[ ]` **3D Voxel View** — React Three Fiber + MagicaVoxel (see `ROADMAP_3D_VOXEL.md`)

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
- `[x]` Ecosystem inference centralized (Fortuna, Yantra4D, PhyneCRM → Selva proxy)
- `[x]` Service resource registry (8 external accounts tracked)
- `[x]` Email delivery verified (Resend Pro, madfam.io domain)
- `[x]` 6 selva pods healthy (nexus-api, workers, gateway, colyseus, office-ui, admin)
- `[x]` ArgoCD synced to latest commit
- `[x]` Dev-bypass rejected in production auth
- `[ ]` Anthropic API credit balance > $0
- `[ ]` Stripe MX in live mode (sk_live_)
- `[ ]` Gateway secrets injection (DingTalk, Feishu, etc.)
- `[ ]` Docker socket sandboxing for worker pods
