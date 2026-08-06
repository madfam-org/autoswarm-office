# Operator Backlog (post-2026-05-04 sprint)

> Single source of truth for everything that's BLOCKED ON A HUMAN DECISION
> after the 28-PR production-truthfulness sprint of 2026-05-04. Every
> item below is unblocked from the engineering side; what's missing is
> a vendor pick, a budget approval, a config flip, or a manual operation.
>
> **Wave 1 operator runbook (2026-06-22):** [docs/WAVE1_OPERATOR_RUNBOOK.md](WAVE1_OPERATOR_RUNBOOK.md)
> — OTel bootstrap, trace proof, Sentry probe, Run 4b, DR drill, gate bundle.
>
> **Full remediation index (2026-06-22):** [docs/FULL_REMEDIATION_PLAN_2026-06-22.md](FULL_REMEDIATION_PLAN_2026-06-22.md)
> — master wave plan sequencing Phase 0, commercial GA, and live prod findings.
>
> **Read this first** when picking the work back up. For the **full sprint schedule**
> (4 weeks, engineering backlog, exit checklist), see
> [docs/PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md).
> For the **platform-wide commercial GA contract**, see
> [docs/COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md)
> before declaring any tenant lane generally available.
> For **GTM strategy, wedges, and the path to full GA**, see
> [docs/COMMERCIAL_GA_STRATEGY_AND_IMPLEMENTATION_2026-06-22.md](COMMERCIAL_GA_STRATEGY_AND_IMPLEMENTATION_2026-06-22.md).
> Then read [docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md)
> for the full north-star plan (Phases 0–6), then
> [ROADMAP.md](../ROADMAP.md) for product phase context and
> [CHANGELOG.md](../CHANGELOG.md) for what shipped.
>
> **Doc truth remediation (2026-05-30):** Port, health, and count claims
> were reconciled against code + prod. Canonical reference:
> [docs/PORTS.md](PORTS.md). Config fixes (`PUBLIC_APP_URL`, `CORS_ORIGINS`,
> gateway HTTP probes) ship in-repo — run `./scripts/verify-doc-truth.sh`
> after Enclii promote; A2A url check passes only post-deploy.

---

## How to use this doc

Each item lists:
- **What** — concrete action to take
- **Why blocking** — what stays broken / degraded until it's done
- **Owner** — who decides / executes
- **Unblocks** — what becomes possible after this lands
- **Cross-refs** — the RFCs / runbooks / PRs with the detail

Items are roughly priority-ordered. Highest value at top.

**Program mapping:** Tier 1–3 items = [Autonomous Operations Program Phase 0](AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-0--operational-foundation-2-3-weeks). Tier 5 items = Program Phases 4–5. Completing Phase 0 gates Phase 1 (live revenue loop).

**Phase 2 engineering (2026-05-30):** Campaign API, worker graph, scheduled social
executor, schedule materializer, and office-ui Campaign Dashboard are merged to
`main` (#179). **API operator gate met** via `./scripts/verify-campaign-loop.sh --staging`.
Optional UI soak remains; Phase 0 remediation is the critical path — see
[PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md).

## 2026-06-04 readiness snapshot (tenant slice + full GA)

- **MADFAM tenant slice (`admin@madfam.io`) in prod:** ~85–90% of unrestricted in-slice operations is now enabled, with tenant isolation and scoped tooling patterns in place.
- **Selva production-truthful baseline:** ~88–92% once core remediations are counted.
- **Full commercial GA (all tenants):** currently **~58–65%**; blocked primarily by evidence and operations gaps, not by fundamental platform capabilities.

Current ROI priority order to close this gap is aligned with this backlog:

1. **OTel + Sentry productionization (Tiers 1–2, items 1–2)** → actionability on incidents.
2. **Billing correctness (Tier 2, item 3)** → proven revenue attribution and tier enforcement.
3. **Load calibration + DR evidence (Tier 3, items 5–6)** → safe scaling and recovery claims.
4. **Cross-workstream hardening (Tiers 5+)** → multi-tenant evidence, residency, failover readiness.

Commercial-GA correctness hardening (GA-001..GA-008) is now closed at repo
level and tracked as Phase 0.8 evidence rather than an operator tier.

Keep this as the default triage order when multiple items are unblocked.

For a day-by-day execution checklist, see [docs/REMEDIATION_EXECUTION_PLAN_2026-06-04.md](./REMEDIATION_EXECUTION_PLAN_2026-06-04.md).

### Engineering no-go items surfaced on 2026-06-04

These are not operator-blocked and are now closed at repo level. Evidence lives
in [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md)
and [CI_TEST_SCOPE.md](CI_TEST_SCOPE.md):

- Gateway auto-dispatch includes `X-Selva-Tenant-Org` on worker-token calls.
- Gateway auto-dispatch graph rules match API-supported `graph_type` values.
- Colyseus department/agent sync carries room tenant context.
- Live campaign scheduling no longer uses placeholder recipients.
- Streaming inference, approval agent names, memory-store compatibility, and
  CI test-scope clarity have explicit fixes or documentation.

---

## 2026-07-19 update (monetization spine + engagement UI)

Thirteen PRs (#232–#246) merged to `main` on 2026-07-19. What changed for the
operator:

- **Selva can now collect, not just meter** — the revenue loop is wired
  end-to-end: **M1** First-Peso checkout (#235) added `DhanamClient.create_checkout()`
  + `POST /billing/checkout` (real call when Dhanam's endpoint exists, else a
  clean `501 "not_configured"` — flip-on-ready), `GET /billing/tiers`, a
  `useCheckout` hook, and a public `/pricing` page (old dead `mailto:` bundle
  CTAs removed). **M2** (#236) turns the dispatch-budget 402 into a one-click
  `UpgradeModal`. **M3** (#237) accrues metered agent-hours
  (`AgentHoursLedger`, migration 0040) for the Tulana-priced SKU. See new
  item 20.
- **HUD compute-token meter is now truthful** (#235, M1.5) — it read a
  hardcoded fake `{used: 0, limit: 10000}`; now reads real `/billing/tokens`
  data.
- **`/metrics` no longer leaks the internal API surface** (#233) — was
  publicly scrapable (every route path + method + error rate). Now guarded:
  Cloudflare-edge (public) requests get `404` unless they carry the service
  token; in-cluster Prometheus scrapes pass unchanged — **ServiceMonitors
  need no change.**
- **`www.selva.town` now 301-redirects to the apex** (#234) — was serving a
  duplicate apex, splitting SEO/cookies.
- **Four E1 engagement surfaces shipped** (#240, #241, #243, #245) — space
  roster (humans + agent-citizens), first-run welcome tour, ⌘K command
  palette, and office-size onboarding with a live procedural preview (first
  real consumer of `@selva/map-gen`). Office-size now server-persisted
  (`TenantConfig.office_size`, migration 0041, #246).
- **CI flake fixed** (#232 / #244) — `OutboundIdentityForm` blur test;
  #244 fixed the real GET→reset race.

**New operator blocker (see item 20 below): migrations 0040 AND 0041 need
applying in prod.** *(Resolved 2026-08-06 — see item 20.)* The deploy pipeline still does not auto-run migrations.
An ArgoCD PreSync migration hook (**PR #238**) is **open, not merged**
(blocked on a live Kyverno dry-run pending an SSH-tunnel outage). Until #238
merges, each new migration needs a manual `alembic upgrade head`.

**Still open after this update:** apply migrations 0040/0041 in prod (item 20 — **done 2026-08-06**),
arm the inference budget gate (item 14), wire real collection (Dhanam
`/billing/checkout` endpoint + Tulana usage reporter — items 3 and 20),
per-product AI attribution (item 13), plus the prior 2.4.0 Tier 7 items —
manual prod deploy gate (item 15), OTel/Sentry on `inference-gateway`
(item 16), branch protection on `main` (item 17), PUBLIC-repo state (item 18),
and the missing RFC 0031 / 0034 files (item 19).

---

## 2026-07-18 update (RFC 0034 metering + realtime-office stabilization)

Seven PRs (#222–#229) merged to `main` on 2026-07-18. What changed for the
operator:

- **`inference-gateway` is now a real production Deployment** (RFC 0034 P2) —
  the extracted, sole home of the `/v1` inference proxy, 2 replicas in the
  `selva` namespace. Selva now runs **7 Deployments** (admin, colyseus,
  gateway, inference-gateway, nexus-api, office-ui, workers) — anywhere this
  doc or a runbook says "6 Deployments," add `inference-gateway`.
- **USD usage ledger now accrues** (#222) — was recording zeros
  (key-style mismatch + unauthenticated worker metering + body-`org_id`
  trust). Metering, auth, and org-from-caller are fixed. See new item 13.
- **Streaming inference now metered** (#229) — the proxy previously returned
  before recording; now writes the ledger on stream end.
- **Virtual office joinable + verified in prod** (#223) — colyseus matchmake
  routes now mount, package trio aligned, client forwards its auth token.
  Verified end-to-end on `selva.town/demo` 2026-07-18.
- **`main` un-blocked** (#224) — was 5 days red (PR #219 merged past failing
  checks; no branch protection). X/LinkedIn direct-post tools now ship dark
  (absent from the registry unless `SELVA_X_POST_ENABLED` /
  `SELVA_LINKEDIN_POST_ENABLED` are armed). `mcp` bumped 1.27.0 → 1.28.1
  (CVE-2026-52869 / 52870 / 59950, all HIGH).
- **Staging nexus-api recovered** (#225) — 28h `CreateContainerConfigError`
  from a prod-only `selva-secrets` ref in the staging overlay; remapped
  `DHANAM_CATALOG_APPLY_SECRET` to `selva-staging-secrets`. Now 1/1 Running.
- **New tropical solarpunk day/night UI + pre-join A/V screen** (#227) — live
  in prod; theme resolves day/night from the local clock.

**Still open after this update** (see new Tier 7 below): arm the inference
budget gate, wire the manual prod deploy gate, wire OTel/Sentry on
`inference-gateway`, enable branch protection on `main`, fix per-product AI
attribution, resolve the PUBLIC-repo state, and create the missing RFC 0031 /
0034 files.

---

## Tier 1 — Blocks production observability (do first)

### 1. Wire OTel exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`)

- **Status (2026-06-04)**: K8s optional secret refs shipped on all 6
  Deployments (`infra/k8s/production/patches/observability-*.yaml`).
  `./scripts/verify-observability-trace.sh` now dispatches with a generated
  W3C trace ID and can poll a read-only Tempo/Grafana query endpoint for that
  exact trace. Operator action remains: create secret + run trace proof.
- **What**: Pick a backend, provision the endpoint URL + auth header,
  set the env var on every service in production K8s. Verify a trace
  flows end-to-end for one request path (e.g.,
  `POST /api/v1/swarms/dispatch` → worker pickup → checkpoint write).
- **Why blocking**: Today there are zero distributed traces in
  production. SLO dashboards (`infra/grafana/dashboards/selva-slos.json`),
  burn-rate alerts (`infra/prometheus/alerting-rules.yml`), and the
  load-test runbook all become useful only once traces flow. PR #137
  wired the propagation; PR #129 + #139 wired the SLO definitions +
  rules; this is the missing link.
- **Owner**: Operator decides/provisions vendor; engineering verifies the
  trace proof with `./scripts/verify-observability-trace.sh --require-trace`.
- **Unblocks**: Cross-service trace correlation, SLO dashboards going
  live, burn-rate alerts firing on real data.
- **Cross-refs**:
  - [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
    — recommendation: Grafana Cloud Free → Pro for traces+logs+metrics
  - [docs/SLOS.md](SLOS.md) §8 — implementation cross-refs
  - PR #137 (W3C trace propagation), #129 (SLO defs), #139 (rules + dashboard)

### 2. Provision Sentry per-service DSNs

- **Status (2026-06-04)**: Per-service optional `SENTRY_DSN` /
  `NEXT_PUBLIC_SENTRY_DSN` secret refs are wired, and office-ui source-map
  upload is repo-complete behind `SENTRY_AUTH_TOKEN` + `SENTRY_ORG`.
  Operator creates DSN keys in `selva-observability-secrets` per
  `infra/k8s/production/observability-secrets-template.yaml`.
- **What**: Create separate Sentry projects (nexus-api, workers, gateway,
  colyseus, office-ui, and admin if enabled), grab the DSN for each, set the
  per-service env var (`SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN`), set GitHub
  source-map upload credentials, then trigger a synthetic `RuntimeError` in
  staging to verify capture.
- **Why blocking**: Today `init_sentry()` runs in every service but
  the DSNs are unset, so errors don't flow. Production incident
  visibility is ~0 outside of K8s pod logs.
- **Owner**: Operator decides/provisions plan; engineering verifies capture.
- **Unblocks**: Production error capture; Sentry alerts; release
  health tracking.
- **Cross-refs**:
  - [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
    — recommendation: Sentry Team plan EU region (~$26/mo)
  - 5 separate projects so error budgets don't pollute each other

---

## Tier 2 — Blocks billing / compliance correctness

### 3. Configure Dhanam price→tier map + Selva webhook

- **Status (2026-06-04)**: **Selva + Dhanam staging fan-out wired** (reconcile is
  idempotent — re-run if `PRODUCT_WEBHOOK_URLS` drifts empty). The verifier now
  checks canonical tier coverage from `infra/pricing/selva-tiers.json` and can
  fail hard with `--require-all`. **Remaining:** map Stripe price IDs → tiers
  in Dhanam catalog (prod + staging checkout paths), then run
  `./scripts/verify-dhanam-price-tier-map.sh --staging --require-all`.
- **What**: In **Dhanam** (canonical Stripe/POS router), map production
  Stripe price IDs to `starter`, `professional`, `enterprise`. Point Dhanam
  billing webhooks at Selva
  `POST /api/v1/billing/webhooks/dhanam` with HMAC via
  `DHANAM_WEBHOOK_SECRET`. Set `BILLING_VIA_DHANAM=true` on nexus-api
  (default). Do **not** populate `STRIPE_PRICE_TO_TIER_MAP` in Selva —
  Dhanam normalizes events and sends tier in the webhook payload.
- **Why blocking**: Without Dhanam→Selva webhooks, subscription tier stays
  at defaults and dispatch budget enforcement mis-tiers customers. Direct
  Stripe webhooks to Selva return **503** when `BILLING_VIA_DHANAM=true`.
- **Owner**: Operator (Dhanam + Stripe Dashboard access required).
- **Unblocks**: Live billing via Dhanam checkout; tier cache updates in
  Redis; `FEATURE_STRIPE_MXN_LIVE` only as break-glass with
  `BILLING_VIA_DHANAM=false`.
- **Cross-refs**:
  - `apps/nexus-api/nexus_api/services/billing_sync.py` — canonical sync
  - `apps/nexus-api/nexus_api/routers/billing.py` — Dhanam webhook
  - `infra/pricing/selva-tiers.json` — daily limits per tier
  - `packages/tools/src/selva_tools/builtins/billing_tools.py` — checkout
    via `DHANAM_API_URL/v1/billing/checkout`

### 4. Flip `AUDIENCE_FILTER_ENABLED=true` — **DONE (prod)**

- **Status**: Production configmap sets `AUDIENCE_FILTER_ENABLED: "true"`
  (`infra/k8s/production/configmap.yaml`). Platform/tenant boundary is
  enforced on workers + nexus-api.
- **Verify**: No spike in legitimate-traffic 403s; spot-check
  `audience_shadow_block` logs are absent under enforce mode.
- **Cross-refs**:
  - [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md) § Production status
  - Shadow procedure still applies when standing up **new** environments.

### 13. Per-product AI attribution collapses to `platform` / `service:worker`

- **Status (2026-07-18)**: The RFC 0034 USD usage ledger now records
  non-zero usage (PR #222 fixed key-style mismatch + auth + org-from-caller;
  PR #229 metered streaming). **But** all shared-token callers still collapse
  to `org_id='platform'`, `caller='service:worker'`, so usage cannot be
  attributed per product/tenant for those calls.
- **What**: Give shared-token callers (workers, ecosystem services) a
  per-product / per-tenant identity so ledger rows attribute to the real
  consumer instead of the `platform` / `service:worker` sentinel.
- **Why blocking**: Revenue attribution and any per-product AI cost
  reporting is impossible while every shared-token call books to `platform`.
- **Owner**: Engineer (implementation) — no operator decision required.
- **Unblocks**: Per-product AI cost attribution; accurate usage-based
  billing for shared-token consumers.
- **Cross-refs**: PR #222 (`_normalize_usage`, org-from-caller), PR #229
  (streaming meter). Missing RFC file `docs/rfcs/0034-*` (see Tier 7).

---

## Tier 3 — Validates resilience claims

### 5. Run k6 100-concurrent-tasks load scenario in staging

- **Status (2026-05-30)**: `.github/workflows/load-test.yml` ships with
  `./scripts/run-staging-load-full.sh` (requires staging rate-limit patches in
  `patch-nexus-api.yaml`; pre-run `./scripts/drain-staging-task-queue.sh`).
  **Runs 1–3 recorded** in `docs/LOAD_TEST_2026-Q2.md` — none pass hard thresholds;
  Run 4 needs lighter graph or scaled nexus-api replicas.
- **What**: Provision `k6` in the operator workstation or staging
  CI runner. Provision a staging API token. Run
  `k6 run -e BASE_URL=https://staging-api.selva.town -e AUTH_TOKEN=<token> tests/load/concurrent-100-swarmtasks.js`.
  Capture summary output. Fill in the Results table in
  `docs/LOAD_TEST_2026-Q2.md`. Adjust production config based on
  observed values.
- **Why blocking**: Today's `MAX_CONCURRENT_TASKS=3`,
  `dispatch_rate_limit=10`, `TIER_DAILY_TASK_LIMIT.{starter,pro,enterprise}=50/200/1000`
  are guesses. The next pricing or scaling decision is uncalibrated.
- **Owner**: Operator (staging access).
- **Unblocks**: Data-driven production limits; SLO calibration;
  pricing decisions backed by evidence.
- **Cross-refs**:
  - PR #128 (scenario + runbook)
  - [docs/LOAD_TEST_2026-Q2.md](LOAD_TEST_2026-Q2.md)
  - [docs/SLOS.md](SLOS.md) §2 — Tier 1 p99 < 1500ms target this
    scenario validates

### 5c. k6 Run 4 — calibration graph + threshold pass (engineering)

- **Status (2026-06-04)**: **Partial — repo guardrails shipped; live Run 4b pending.**
  - **Shipped:** `graph_type=calibration`, worker/API pipeline fixes (`NEXUS_API_URL`, events RLS),
    queue-stats gauges, `./scripts/run-staging-load-calibration.sh`,
    `infra/k8s/overlays/staging-load`, and
    `./scripts/verify-staging-load-run4b-preflight.sh`.
  - **Run 4:** 80.9% dispatch 2xx (vs 44% Run 3); **hard thresholds still fail** (p99 10s,
    queue_depth max 1209) — single `nexus-api` replica during run; Argo drift vs kustomize `replicas: 2`.
  - **Next:** apply `kubectl apply -k infra/k8s/overlays/staging-load`,
    pass `./scripts/verify-staging-load-run4b-preflight.sh --require-live`,
    drain, run `./scripts/run-staging-load-calibration.sh`, then revert
    `kubectl apply -k infra/k8s/overlays/staging`. Session log:
    [SESSION_2026-05-30_PHASE0_RUN4.md](SESSION_2026-05-30_PHASE0_RUN4.md).
- **What**: Re-run `./scripts/run-staging-load-calibration.sh` until hard thresholds pass;
  optional `worker_in_flight` gauge accuracy follow-up.
- **Owner**: Engineer (selva-office).
- **Unblocks**: Data-driven prod limits; Phase 0 gate 0.4; PP.5 promote confidence.
- **Cross-refs**: Epic E1–E3 in [PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md)

### 5b. Staging campaign loop soak (Phase 2 gate)

- **Status (2026-05-30)**: **DONE (API loop green)** —
  `./scripts/verify-campaign-loop.sh --staging` passes end-to-end including
  `tulana-feedback (200)` after Tulana `0161187` + cache-bust deploy
  (`cc4d3b645469…`). Use worker auth via `STAGING_WORKER_API_TOKEN` in CI.
- **What**: Optional UI soak on `https://staging.selva.town/office` → **Campaigns**.
- **Why blocking**: Phase 2 program gate required a proven Tulana → Selva → Phynd
  → Tulana loop — **API path now proven**; optional UI soak remains.
- **Owner**: Operator (Janua staging login + Tulana export JSON).
- **Unblocks**: Phase 3 phygital work; autonomy graduation for campaign lanes.
- **Cross-refs**:
  - [docs/INTEGRATION.md](INTEGRATION.md) — campaign endpoints + UI
  - [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md)
  - `./scripts/drain-staging-task-queue.sh` — break-glass Redis stream trim + consumer group reset (pre–load-test)
  - `./scripts/reconcile-dhanam-selva-webhook.sh` — wire Dhanam `PRODUCT_WEBHOOK_URLS` → Selva staging
  - `./scripts/verify-dhanam-price-tier-map.sh --staging --require-all` — strict GA gate for Dhanam price→tier + webhook fan-out coverage
  - `./scripts/bootstrap-staging-observability.sh` — create `selva-observability-secrets` (Tier 1)

### 3b. Deploy Tulana buyer-signal ingest route — **DONE (2026-05-30)**

- **Status**: Shipped in `madfam-org/tulana@0161187` + digest `cc4d3b645469…`.
  `./scripts/verify-campaign-loop.sh --staging` → `tulana-feedback (200)`.
- **Unblocks**: Full Phase 2 Tulana ↔ Selva feedback loop; buyer-signal WTP evidence.
- **Cross-refs**:
  - `apps/nexus-api/nexus_api/services/tulana_feedback.py`
  - [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md) § Tests

### 6. Run backup/restore drill in staging

- **Status (2026-06-04)**: **Repo guardrails shipped; live drill pending.**
  `scripts/run-db-restore-drill.sh` preflights and executes the drill only
  with `DR_DRILL_EXECUTE=yes`, a named non-production restore target, and
  explicit source/target database URLs or an existing backup file. Evidence
  lands in `docs/dr-drills/` and is checked by
  `scripts/verify-dr-drill-evidence.sh`.
- **What**: Take a fresh prod backup or a declared backup file, restore it
  into a clean staging instance through the guarded wrapper, measure RTO, verify
  off-site/cross-region storage destination, document RPO, and schedule
  recurring monthly drill.
- **Why blocking**: Today `Makefile` has the targets but no evidence
  of regular testing. The "what's our RTO if we lose the DB tomorrow"
  question is unanswered.
- **Owner**: Operator (production backup access + staging restore).
- **Unblocks**: Confidence in disaster recovery; SOC 2 + LFPDPPP audit
  evidence.
- **Cross-refs**:
  - `Makefile` `db-backup` / `db-restore` / `db-verify-backup` targets
  - `Makefile` `db-drill-preflight` / `db-drill` targets
  - `scripts/run-db-restore-drill.sh`
  - `scripts/verify-dr-drill-evidence.sh`
  - `docs/dr-drills/`
  - `infra/k8s/production/backup-cronjob.yaml`
  - RFC 0021 §10 — failover RFC depends on backup evidence

---

## Enclii adapter gaps (record — do not normalize raw kubectl)

Tracked in [PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md) § Gap analysis.

| Gap | Break-glass today | Target |
|-----|-------------------|--------|
| Staging Alembic Job | `scripts/run-staging-migrations.sh` | Enclii pre-deploy migration hook |
| Observability secret | `scripts/bootstrap-staging-observability.sh` | Enclii secret provisioning |
| Dhanam webhook drift | `scripts/reconcile-dhanam-selva-webhook.sh` | Durable ExternalSecret merge in Dhanam |
| Staging `DATABASE_ADMIN_URL` | Drain script cannot fail DB rows under strict RLS | Enclii env for `app_admin` role |

---

## Tier 4 — Schedule the recurring rituals

### 7. Schedule first quarterly secret rotation

- **Status (2026-06-04)**: **Repo schedule shipped; external calendar
  confirmation pending.** The Q3 window is recorded in
  `docs/secret-rotations/2026Q3-schedule.md` and verified by
  `./scripts/verify-secret-rotation-schedule.sh`.
- **What**: Confirm the external ops calendar event for Q3 2026 →
  2026-07-07 14:00 America/Mexico_City with the runbook link. Run
  `./scripts/rotate-secret.sh --all --namespace=selva` from a workstation
  with `kubectl` access + bash 4+. Now safely includes
  `consent-ledger-signing` (PR #145 closed the §6 limitation).
- **Why blocking**: Three production secrets (`WORKER_API_TOKEN`,
  `CONSENT_LEDGER_SIGNING_SECRET`, `COLYSEUS_SERVICE_TOKEN`) have
  never been rotated. SOC 2 CC6.1 cadence is 90d. The validators
  catch "I forgot to set this" but not "I set this 12 months ago."
- **Owner**: Operator (kubectl access + brew bash on macOS).
- **Unblocks**: SOC 2 CC6.1 compliance evidence; reduced blast
  radius from any single-key compromise.
- **Cross-refs**:
  - [docs/SECRET_ROTATION_POLICY.md](SECRET_ROTATION_POLICY.md)
  - [docs/secret-rotations/2026Q3-schedule.md](secret-rotations/2026Q3-schedule.md)
  - `scripts/verify-secret-rotation-schedule.sh`
  - `scripts/rotate-secret.sh` — atomic rotation tool
  - PR #138 (script + policy), PR #145 (per-period key tracking
    that made consent-ledger-signing safe to rotate)

### 8. Quarterly SLO review

- **What**: Pick a date 90 days out (next: 2026-08-04). Walk through
  [docs/SLOS.md](SLOS.md) §7 checklist: did we hit each SLO over the
  last 90d? Were burn-rate alerts noisy? Reclassify endpoints? Add
  new endpoints to §4? Output: `docs/SLO_REVIEW_2026Q3.md`.
- **Why blocking**: SLOs that aren't reviewed drift into uselessness.
  A doc that nobody updates becomes a doc nobody reads.
- **Owner**: Engineer-led with operator review.
- **Unblocks**: Trustworthy production SLO commitment.
- **Cross-refs**: [docs/SLOS.md](SLOS.md) §7

---

## Tier 5 — Architecture (multi-week implementations behind RFCs)

### 9. Approve Kafka cluster + cost for CDC RFC #0019

- **What**: Decide where the audit Kafka cluster lives (existing
  `internal-devops` K8s vs dedicated). Approve the ~$300-800/mo
  cost (managed AWS MSK + Confluent Schema Registry + Kafka Connect
  workers). Then engineer can execute Phase A pilot (Selva CDC) in
  ~2 weeks.
- **Why blocking**: Manual `emit_event_db` discipline doesn't scale
  past 6+ services. Without CDC, cross-service audit queries (per
  RFC §1 examples) remain unanswerable.
- **Owner**: Operator (cost approval + cluster ownership decision).
- **Unblocks**: 10-week phased CDC migration per RFC §4. Eventually
  retires the manual `emit_event_db` discipline (PR #130/131/133)
  in favor of automatic per-row CDC capture.
- **Cross-refs**: [docs/rfcs/0019-cross-service-cdc-audit-topic.md](rfcs/0019-cross-service-cdc-audit-topic.md)

### 10. Provision MX-region cluster for residency RFC #0020

- **What**: Stand up a Postgres + Redis + K8s cluster in a Mexican
  AWS / GCP region. Plumb `DATABASE_URL_MX` env var. Engineer
  executes the per-region routing helper + `tenant_configs.data_residency_region`
  ENUM column + onboarding flow per RFC §4.
- **Why blocking**: Mexican LFPDPPP / SAT requirements for CFDI
  data residency are active. New SAT-bound tenants today land in
  whatever region the single shared cluster lives in. First
  enforcement audit would surface this gap.
- **Owner**: Operator (cluster provisioning) + engineer
  (implementation, ~3-4 weeks).
- **Unblocks**: SAT-compliant onboarding for new Mexican tenants.
  Then RFC 0021 multi-region failover becomes implementable.
- **Cross-refs**:
  - [docs/rfcs/0020-per-tenant-data-residency.md](rfcs/0020-per-tenant-data-residency.md)
  - [docs/rfcs/0021-multi-region-failover.md](rfcs/0021-multi-region-failover.md)

### 11. Cut over A2A bridge to per-caller tenants (RFC #0018 Phase D)

- **What**: Migration 0029 (PR #136) scaffolded `external_a2a_callers`
  table. Now write the bridge cutover: `_dispatch_a2a_task` and
  `_get_a2a_task_status` in `apps/nexus-api/nexus_api/main.py`
  switch from `tenant_session(org_id="a2a-external")` to looking up
  the per-caller tenant row by `agent_card_url`. Migrate any
  in-flight `a2a-external` rows.
- **Why blocking**: Today every A2A caller shares the synthetic
  `a2a-external` org. No quota / billing / consent / per-caller
  audit. Acceptable for 0 paying A2A callers; broken on first one.
- **Owner**: Engineer (~1 week implementation behind RFC).
- **Unblocks**: Real A2A monetization + per-caller observability +
  per-caller revocation.
- **Cross-refs**: [docs/rfcs/0018-a2a-external-tenant-model.md](rfcs/0018-a2a-external-tenant-model.md) §4 Phase D

---

## Tier 6 — One-off operator merges

### 12. Merge PR #125 (mypy wave 7) — **DONE**

- **Status**: Merged to `main` (2026-05-04). Packages mypy ratchet is 0.

---

## Tier 7 — Infra + governance gates (surfaced 2026-07-18)

### 14. Arm the inference budget gate (`BUDGET_GATE_ENABLED`)

- **Status (2026-07-19)**: **Still unset in all manifests.** No inference
  spend cap is enforced today. The USD usage ledger accrues correctly
  (PR #222 / #229) and the M2 upgrade moment (PR #236) already surfaces the
  dispatch-budget 402 to users, so arming the gate is meaningful and the
  upgrade path is in place.
- **What**: Set `BUDGET_GATE_ENABLED=true` on the services that enforce the
  cap after a staging smoke confirms the ledger and cap behave as expected.
- **Why blocking**: Without it, inference spend is uncapped — a runaway
  workflow or provider price change has no automatic backstop.
- **Owner**: Operator (config flip after staging smoke).
- **Unblocks**: Enforced inference spend ceiling per the RFC 0034 ledger.
- **Cross-refs**: PR #222, #229 (usage ledger correctness prerequisites).

### 15. Wire the manual prod deploy gate (Pattern B)

- **Status (2026-07-18)**: **Inert.** The declared Pattern B manual gate is
  not wired. The live path is the legacy direct-to-prod pipeline
  (`deploy.yml` on every `main` push → `infra/k8s/production` → ArgoCD
  auto-sync). `rollback-prod.yml` writes to `infra/k8s/overlays/production`,
  which ArgoCD does **not** watch — so the documented rollback path does not
  reach prod.
- **What**: Wire the Pattern B manual approval gate into the prod deploy
  path, and point `rollback-prod.yml` at the overlay ArgoCD actually watches
  (`infra/k8s/production`) — or repoint ArgoCD at the overlay the rollback
  writes.
- **Why blocking**: Every `main` push auto-ships to prod with no manual gate,
  and the advertised rollback is a no-op against the live cluster.
- **Owner**: Operator + engineer (pipeline wiring).
- **Unblocks**: Gated prod releases; a rollback path that actually reaches prod.
- **Cross-refs**: `.github/workflows/deploy.yml`,
  `.github/workflows/rollback-prod.yml`, `infra/k8s/production`,
  `infra/k8s/overlays/production`.

### 16. Wire OTel/Sentry on `inference-gateway` (RFC 0034 P2)

- **Status (2026-07-18)**: The extracted `inference-gateway` Deployment
  (2 replicas, `selva` namespace) has **no OTel/Sentry wiring**. Tier 1
  items 1–2 wired observability on the other services; the new gateway was
  not covered.
- **What**: Add the same OTel exporter + Sentry DSN env refs to the
  `inference-gateway` Deployment as the other services carry, and verify a
  trace + a synthetic error flow.
- **Why blocking**: The `/v1` inference proxy is now the gateway's sole home;
  inference-path incidents have zero trace/error visibility until this lands.
- **Owner**: Engineer (manifest wiring) + operator (same DSNs/endpoint as
  Tier 1).
- **Unblocks**: Inference-path trace correlation and error capture.
- **Cross-refs**: Tier 1 items 1–2; RFC file `docs/rfcs/0034-*` (missing — see item 19).

### 17. Enable branch protection on `main`

- **Status (2026-07-18)**: **No branch protection.** PR #219 merged past
  failing checks and left `main` red for 5 days (fixed by PR #224).
- **What**: Enable required status checks + review on `main` so a red PR
  cannot merge.
- **Why blocking**: Nothing prevents merging past failing CI; `main` can go
  red silently and stay red.
- **Owner**: Operator (GitHub repo settings).
- **Unblocks**: A `main` that stays green; safer merge discipline.
- **Cross-refs**: PR #219 (the merge-past-red incident), PR #224 (the fix).

### 18. Resolve PUBLIC-repo state vs sanitization decision

- **Status (2026-07-18)**: The repo is **PUBLIC**, while
  `docs/PUBLIC_REPO_SANITIZATION_OWNER_DECISION_2026-06-01.md` says
  "blocked, not sanitized." Doc and reality disagree.
- **What**: Either sanitize per the decision doc and confirm public is
  intended, or flip the repo private and update the doc — reconcile the two.
- **Why blocking**: The repo is public without the sanitization the owner
  decision required.
- **Owner**: Operator (visibility decision + repo settings).
- **Unblocks**: A repo state that matches the recorded owner decision.
- **Cross-refs**: `docs/PUBLIC_REPO_SANITIZATION_OWNER_DECISION_2026-06-01.md`.

### 19. Create missing RFC files 0031 and 0034

- **Status (2026-07-18)**: **Documentation debt.** Merged PRs cite RFC 0031
  and RFC 0034, but neither file exists under `docs/rfcs/`.
- **What**: Author `docs/rfcs/0031-*.md` and `docs/rfcs/0034-*.md` capturing
  the decisions the merged PRs already implemented. Do not fabricate content —
  write them from the actual implemented behavior (RFC 0034 = inference
  gateway extraction + USD usage ledger; 0031 subject per the citing PRs).
- **Why blocking**: The architecture record is incomplete; readers can't
  trace the gateway extraction or usage-ledger design to an RFC.
- **Owner**: Engineer (author from implemented behavior).
- **Unblocks**: A complete RFC index; traceable design rationale for RFC
  0034 work shipped in PRs #222 / #229 and the gateway extraction (P2).
- **Cross-refs**: `docs/rfcs/`, PR #222, #229 (RFC 0034 implementation).

### 20. Apply migrations 0040 and 0041 in prod (no auto-migration hook) — **DONE (2026-08-06)**

- **Status (2026-08-06)**: **RESOLVED.** Recon found prod already at 0040;
  0041 applied today via `scripts/ops/create-selva-migrator-and-apply-0041.sh`
  (landed by PR #262 from the operator's stash). The script also created the
  `selva_migrator` role (member of `enclii` + `autoswarm`, default privileges
  granting DML to the app role) and stored
  `selva-secrets/migration-database-url` (direct :5432, not pgbouncer) — so the
  PreSync migrate-job from PR #238 (since merged) now has its migration
  identity and future migrations run hands-off. Verified in prod:
  `alembic current` = `0041 (head)`; `tenant_configs.office_size`
  (varchar, nullable) exists; app role reads `tenant_configs` normally.
- **Status (2026-07-19)**: **Two new migrations unapplied in prod.** The
  monetization/onboarding work shipped **migration 0040** (`AgentHoursLedger`,
  PR #237) and **migration 0041** (`TenantConfig.office_size`, PR #246), but
  the deploy pipeline still does not auto-run migrations. The ArgoCD PreSync
  migration hook (**PR #238**) is **open, not merged** — blocked on a live
  Kyverno dry-run pending an SSH-tunnel outage.
- **What**: Until #238 merges, run `alembic upgrade head` manually against
  prod after each deploy that adds a migration (0040 + 0041 now). Then land
  #238 to make this automatic.
- **Why blocking**: The M3 agent-hours ledger and office-size persistence
  read/write tables that do not exist in prod until the migrations apply;
  those code paths fail against an un-migrated database.
- **Owner**: Operator (manual `alembic upgrade head` now) + engineer/operator
  (merge #238 to automate).
- **Unblocks**: M3 accrual and office-size persistence working in prod;
  hands-off migration on future deploys once #238 lands.
- **Cross-refs**: PR #237 (0040), PR #246 (0041), PR #238 (PreSync hook —
  open); migrations under `apps/nexus-api/alembic/versions/`.

### 21. Wire real revenue collection (Dhanam checkout endpoint + Tulana reporter)

- **Status (2026-07-19)**: **M1 is flip-on-ready; collection not yet live.**
  `POST /billing/checkout` (PR #235) makes a real call when Dhanam's
  `/billing/checkout` endpoint exists, else returns a clean
  `501 "not_configured"`. M3 accrual (PR #237) records agent-hours locally
  but does not yet report usage to Tulana.
- **What**: Confirm/stand up Dhanam's `/billing/checkout` endpoint so the M1
  501 flips to a real session, and stand up the Tulana usage reporter for M3
  agent-hours.
- **Why blocking**: Until Dhanam's checkout endpoint exists, `/pricing` and
  the M2 upgrade modal return `not_configured`; until the Tulana reporter
  exists, M3 hours accrue but are not billed/reported externally.
- **Owner**: Operator (Dhanam endpoint) + engineer (Tulana reporter).
- **Unblocks**: First-peso collection through Selva checkout; external
  billing/reporting of metered agent-hours.
- **Cross-refs**: PR #235 (M1 checkout, flip-on-ready), PR #237 (M3 accrual);
  item 3 (Dhanam price→tier map).

---

## Index of related docs (for orientation)

| File | Purpose |
|---|---|
| [AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md) | **North star** — Phases 0–6 toward full autonomous digital ops |
| [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md) | Commercial GA no-go gates, immediate hardening, evidence checklist |
| [PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md) | **Sprint plan** — 4-week remediation + engineering backlog |
| [ROADMAP.md](../ROADMAP.md) | Honest scorecard + product phases (F/E). Read after this doc. |
| [CHANGELOG.md](../CHANGELOG.md) | What shipped. v2.3.0 entry covers today's work. |
| [CLAUDE.md](../CLAUDE.md) | Patterns + invariants reference. "Patterns Added in v2.3.0" section is the most current. |
| [docs/SLOS.md](SLOS.md) | Per-endpoint SLO definitions + burn-rate alert specs. |
| [docs/SECRET_ROTATION_POLICY.md](SECRET_ROTATION_POLICY.md) | Quarterly cadence + procedure. |
| [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md) | Operator vendor decision. |
| [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md) | Shadow-soak procedure for the audience flip. |
| [docs/LOAD_TEST_2026-Q2.md](LOAD_TEST_2026-Q2.md) | k6 scenario runbook + results template. |
| [docs/AUDIT_TRAIL_GAP_ANALYSIS.md](AUDIT_TRAIL_GAP_ANALYSIS.md) | SUPERSEDED. Historical gap inventory. |
| [docs/RLS_PHASE_1_5_AUDIT.md](RLS_PHASE_1_5_AUDIT.md) | RLS audit. Closed by PRs #114, #126, #134. |
| [docs/rfcs/0017-image-digest-pinning.md](rfcs/) | Image digest pinning (PR #86 still open). |
| [docs/rfcs/0018-a2a-external-tenant-model.md](rfcs/0018-a2a-external-tenant-model.md) | A2A external tenant. Phase D cutover pending. |
| [docs/rfcs/0019-cross-service-cdc-audit-topic.md](rfcs/0019-cross-service-cdc-audit-topic.md) | CDC audit topic. Phase A pilot pending operator approval. |
| [docs/rfcs/0020-per-tenant-data-residency.md](rfcs/0020-per-tenant-data-residency.md) | Per-tenant data residency. Implementation pending MX-region cluster. |
| [docs/rfcs/0021-multi-region-failover.md](rfcs/0021-multi-region-failover.md) | Multi-region failover. Implementation pending RFC 0020 topology. |
| [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md) | Phase 2 campaign contract (Tulana ↔ Selva ↔ Phynd) |

---

## Picking this work back up — recommended reading order

1. **This doc** — what's blocked + why
2. **[PHASE_0_REMEDIATION_PLAN.md](PHASE_0_REMEDIATION_PLAN.md)** — sprint schedule + engineering backlog
3. **[AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md)** — north star + phase gates
4. **ROADMAP.md "Honest scorecard"** — where we actually are
5. **CHANGELOG.md** — what shipped
6. **The RFC or contract for whichever phase you're executing**

If you're picking up after several weeks: also check `git log --oneline -30`
for any new merges and `gh pr list --state open` for any new PRs that
weren't here at the end of 2026-05-04.
