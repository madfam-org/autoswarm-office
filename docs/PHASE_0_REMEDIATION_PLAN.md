# Phase 0 Remediation & Implementation Plan (2026-Q2)

> **Status:** Accepted (2026-05-30)  
> **Owner:** Selva engineering + MADFAM platform operator  
> **Canonical for:** What to build next in `selva-office`, what requires operator/vendor action, and how it gates the [Autonomous Operations Program](./AUTONOMOUS_OPERATIONS_PROGRAM.md).

---

## Executive summary

Phase 2 **campaign engineering is shipped** (#179): Tulana import → campaign graph → HITL social → Phynd handoff → Tulana buyer-signal, plus the office-ui Campaign Dashboard. Staging proves the **API loop green** via `./scripts/verify-campaign-loop.sh --staging`.

**North-star progress is blocked on Phase 0**, not Phase 2 code. The remaining work splits into three streams:

| Stream | Horizon | Blocks |
|--------|---------|--------|
| **A — Observability** | 3–5 days after vendor creds | SLO alerts, incident response, load-test trace correlation |
| **B — Billing + revenue proof** | 1–2 weeks | Live tier enforcement, Phase 1 gate, prod promote confidence |
| **C — Resilience calibration** | 1 week engineering + 1 drill | Data-driven `MAX_CONCURRENT_TASKS`, dispatch limits, DR evidence |

Until Stream A+B+C complete, **do not promote prod** on campaign features alone. PP.5 cutover requires Phase 0 exit gates in [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md) § Phase 0.

### 2026-06-04 readiness readback (MADFAM tenant slice + commercial GA)

- **Tenant slice in prod (`admin@madfam.io`)**: **~85–90%** — sufficient for in-slice deterministic operations with current safeguards, but not yet formal full GA.
- **Selva-wide production-truthful baseline:** **~88–92%**.
- **Commercial GA for all tenants:** **~58–65%**.

This plan stays the execution vehicle for closing that delta.

For tactical sequencing and day-by-day status, track [docs/REMEDIATION_EXECUTION_PLAN_2026-06-04.md](./REMEDIATION_EXECUTION_PLAN_2026-06-04.md).

| GA blocker | Why it matters | Evidence required before GA statement |
|---|---|---|
| Observability (OTel + Sentry + alert actionability) | Cannot trust incidents without telemetry | End-to-end trace on dispatch path, synthetic staging + prod Sentry capture in each service |
| Revenue correctness | Billing tier and attribution can still drift silently | `Dhanam → Selva` mapping reconciliation, webhook replay tests, attributed paid conversion |
| Load/resilience calibration | Queue sizing and capacity limits still guessed | `Run 4b` threshold pass, calibrated `MAX_CONCURRENT_TASKS`, `dispatch_rate_limit`, DR drill RTO logged |
| Cross-service governance | Manual audit model is being replaced | `rfcs/0019`, RFC 0018 Phase D, tenancy and residency RFC follow-on sign-off |


---

## Baseline — completed (2026-05-30)

### In-repo engineering ✅

| Deliverable | Evidence |
|-------------|----------|
| Campaign API + graph + materializer + UI | `routers/campaigns.py`, `graphs/campaign.py`, `schedule_materializer`, `components/campaigns/` |
| Staging DB bootstrap | Migration 0014 fix, 0038 grants, `scripts/run-staging-migrations.sh` |
| Staging verify gates | `verify-campaign-loop.sh`, `verify-dhanam-billing-path.sh`, `verify-doc-truth.sh` |
| Dhanam webhook handler (Selva side) | `billing.py` — signed POST **200** |
| Load-test harness | `run-staging-load-full.sh`, `drain-staging-task-queue.sh`, Runs 1–4 in [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md) |
| Run 4 calibration graph + scripts | `graphs/calibration.py`, `tests/load/calibration-dispatch.js`, `run-staging-load-calibration.sh` |
| Staging worker/API pipeline fixes | `patch-workers.yaml` (`NEXUS_API_URL`), dispatch `calibration` pattern, events `tenant_session` — see [SESSION_2026-05-30_PHASE0_RUN4.md](./SESSION_2026-05-30_PHASE0_RUN4.md) |
| Staging rate-limit patches | `patch-nexus-api.yaml` (`DISPATCH_RATE_LIMIT`, `RATE_LIMIT_PER_MINUTE`) |
| Worker calibration patch | `patch-workers.yaml` (`MAX_CONCURRENT_TASKS=15`) |
| Tulana buyer-signal | Tulana `0161187` + cache-bust deploy; feedback **200** |

### Operator / cross-repo ✅

| Deliverable | Evidence |
|-------------|----------|
| Staging namespace live | `selva-staging`, ArgoCD app, DNS/tunnel |
| Dhanam staging fan-out (ephemeral) | `./scripts/reconcile-dhanam-selva-webhook.sh` — **must re-run when secret drifts** |
| CI campaign loop secret | `STAGING_WORKER_API_TOKEN` in GitHub |

---

## Gap analysis — what remains

### Phase 0 (hard gate)

| ID | Item | Owner | Status | Next action |
|----|------|-------|--------|-------------|
| 0.1 | OTel exporter | Operator + Enclii | **Open** | Provision Grafana Cloud → `./scripts/bootstrap-staging-observability.sh` → prod mirror |
| 0.2 | Sentry DSNs + source maps | Operator + CI | **Open** | 5 projects + `SENTRY_AUTH_TOKEN` in office-ui CI |
| 0.3 | Dhanam price→tier + prod webhook | Operator (Dhanam/Stripe) | **Partial** | Map Stripe prices in Dhanam; prod `PRODUCT_WEBHOOK_URLS`; fix secret drift |
| 0.4 | k6 calibration pass | Engineering + ops | **Partial** | Run 4 done (80.9% dispatch; thresholds fail) — **Run 4b** at `nexus-api` replicas=2 — [SESSION_2026-05-30_PHASE0_RUN4.md](./SESSION_2026-05-30_PHASE0_RUN4.md) |
| 0.5 | Backup/restore drill | Operator | **Open** | `make db-backup` → restore staging → record RTO/RPO in [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) |
| 0.6 | Staging completion | Operator | **Partial** | Janua staging OAuth client; optional masked DB refresh (PP.6) |
| 0.7 | Secret rotation calendar | Operator | **Open** | Schedule Q3 2026-07-07 per [SECRET_ROTATION_POLICY.md](./SECRET_ROTATION_POLICY.md) |

### Phase 1 (after Phase 0 gate)

| ID | Item | Status |
|----|------|--------|
| 1.1 | LLM provider budget wiring | Partial — budget-gate exists; credits need ops |
| 1.2 | Dhanam compute budgets | ✅ Code path live |
| 1.3 | Attribution closure (utm → checkout → CRM) | **Open** — needs prod Stripe + Phynd trace |
| 1.4 | Live Stripe (`FEATURE_STRIPE_MXN_LIVE`) | **Blocked** on 0.3 |
| 1.5 | Voice/consent on all marketing sends | Code ✅; prod voice_mode completion per tenant |
| 1.6 | HITL graduation baseline | Document in Phase 6 table |

**Phase 1 exit:** One paid conversion traced CRM → Stripe → `tenant_configs.tier` → Karafiel CFDI artifact.

### Phase 2 (operator proof)

| ID | Item | Status |
|----|------|--------|
| 2.x API/UI | All deliverables 2.1–2.7 | ✅ Shipped |
| 2.gate UI soak | Optional manual pass | **Open** — `/office` → Campaigns with Janua staging login |

### Enclii adapter gaps (record, do not normalize)

| Gap | Workaround today | Target adapter |
|-----|------------------|----------------|
| Staging Alembic Job | `scripts/run-staging-migrations.sh` | Enclii pre-deploy migration hook |
| Observability secret | `scripts/bootstrap-staging-observability.sh` | Enclii secret provisioning |
| Dhanam `PRODUCT_WEBHOOK_URLS` drift | `scripts/reconcile-dhanam-selva-webhook.sh` | Dhanam/Enclii durable secret merge |
| Staging `DATABASE_ADMIN_URL` | Break-glass only; drain script marks 0 DB rows | Enclii env for `app_admin` role on staging |
| Staging workers `NEXUS_API_URL` | Fixed in `patch-workers.yaml` (2026-05-30) | Enclii env overlay should override ConfigMap prod URL |
| Staging `nexus-api` replica drift | Manual `kubectl apply -k overlays/staging` | Argo sync policy / HPA pin review |

---

## Implementation schedule (4 sprints)

### Sprint 0 — Observability + billing durability (Week 1)

**Goal:** Streams A + B foundations.

| Day | Engineering (`selva-office`) | Operator / sibling |
|-----|------------------------------|-------------------|
| 1–2 | Wire office-ui Sentry source-map upload in CI (when `SENTRY_AUTH_TOKEN` set) | Create Grafana Cloud + Sentry projects; run bootstrap script on staging |
| 2–3 | Add `scripts/verify-observability-trace.sh` — synthetic dispatch + OTel span check | Verify trace in Grafana; synthetic Sentry error on staging |
| 3–4 | Investigate Dhanam secret drift; document root cause in this doc § Enclii gaps | Map Stripe price IDs in Dhanam catalog; `./scripts/verify-dhanam-price-tier-map.sh --staging` → OK |
| 4–5 | Prod observability secret + staging parity checklist | Set prod `PRODUCT_WEBHOOK_URLS`; align prod `DHANAM_WEBHOOK_SECRET` |

**Exit:** `./scripts/verify-staging-observability.sh` → OK (not SKIP); Dhanam price-tier verify → OK.

---

### Sprint 1 — Load calibration Run 4 + DR (Week 2)

**Goal:** Stream C — defensible concurrency numbers + DR evidence.

#### Run 4 engineering (choose **both** for best signal)

**Track B1 — Calibration graph (in-repo, ~2 days)**

1. Add `graph_type: calibration` (or reuse `literal` workflow) — no LLM, completes in &lt;5s.
2. Add `tests/load/calibration-dispatch.js` — same 100-VU shape as `concurrent-100-swarmtasks.js` but uses calibration graph.
3. Wire `./scripts/run-staging-load-calibration.sh` with drain + budget preflight.
4. Surface `worker_in_flight` via `/api/v1/health/queue-stats` or metrics dashboard (fix gauge gap from Runs 2–3).

**Track B2 — API scale (ops, ~1 day)**

1. Patch staging `nexus-api` replicas → 2 in `patch-nexus-api.yaml` (stateless — safe).
2. Re-run full `concurrent-100-swarmtasks.js` as Run 4b.

**DR drill (operator, ~1 day)**

1. `make db-backup` from prod break-glass path.
2. Restore into staging isolated DB (or PP.6 masked refresh when available).
3. Record measured RTO/RPO in [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) § Drill log.

**Exit:** Run 4b passes hard thresholds in [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md); DR drill row filled.

**Run 4 status (2026-05-30):** B1 complete; B2 partial (kustomize has replicas=2; cluster drifted to 1 during run). See [SESSION_2026-05-30_PHASE0_RUN4.md](./SESSION_2026-05-30_PHASE0_RUN4.md).

---

### Sprint 2 — Revenue loop + prod promote (Week 3)

**Goal:** Phase 1 proof + PP.5.

| Step | Action |
|------|--------|
| 1 | Staging end-to-end: hot lead → dispatch → email draft → approve → Dhanam checkout link |
| 2 | Staging checkout with test Stripe price → Dhanam webhook → Selva tier cache → dispatch budget change |
| 3 | `./scripts/verify-phase0-gates.sh --staging` + campaign loop + Dhanam verify — all green |
| 4 | ≥30 min soak on staging SHA |
| 5 | `promote-to-prod.yml` — pointer update only |
| 6 | `./scripts/verify-doc-truth.sh` on prod post-promote |

**Exit:** Phase 1 attributed conversion documented; prod on staging-validated digest.

---

### Sprint 3 — Phase 2 UI soak + Phase 3 prep (Week 4)

| Step | Action |
|------|--------|
| 1 | Manual UI soak: import Tulana pack → Campaigns dashboard → HITL → handoff → feedback |
| 2 | Schedule Q3 secret rotation + SLO review on ops calendar |
| 3 | Kickoff `epic/phygital-graph` — scaffold `phygital.py` graph shell + quote-truth gate tests |
| 4 | Begin RFC 0019 operator cost conversation (parallel, Tier 5) |

---

## Engineering backlog (selva-office repo)

Priority-ordered PR-sized items:

| # | Epic | Deliverable | Phase |
|---|------|-------------|-------|
| E1 | `epic/ops-foundation` | `calibration` graph + k6 scenario + Run 4 script | 0.4 |
| E2 | `epic/ops-foundation` | `worker_in_flight` / queue depth accuracy in health metrics | 0.4 |
| E3 | `epic/ops-foundation` | Staging `nexus-api` replicas=2 patch | 0.4 |
| E4 | `epic/ops-foundation` | `verify-observability-trace.sh` | 0.1 |
| E5 | `epic/ops-foundation` | office-ui Sentry source maps in CI | 0.2 |
| E6 | `epic/ops-foundation` | Enclii staging migration Job RFC draft → internal-devops | 0.6 |
| E7 | `epic/ops-foundation` | Staging `DATABASE_ADMIN_URL` in secrets template + drain script fix | 0.5 |
| E8 | `epic/revenue-loop-live` | Attribution integration tests (utm → webhook → tier) | 1.3 |
| E9 | `epic/phygital-graph` | `phygital.py` LangGraph scaffold | 3.1 |

---

## Phase 0 exit checklist (copy before Phase 1)

```bash
# Run from repo root after Sprint 0–1
./scripts/verify-doc-truth.sh
./scripts/staging-smoke.sh
./scripts/verify-staging-observability.sh          # must OK, not SKIP
./scripts/verify-dhanam-billing-path.sh --staging
./scripts/verify-dhanam-price-tier-map.sh --staging # must OK, not SKIP
env -u AUTH_TOKEN ./scripts/verify-campaign-loop.sh --staging
./scripts/run-staging-load-calibration.sh          # Run 4 — thresholds pass
# DR drill evidence row filled in docs/DISASTER_RECOVERY.md
```

---

## Doc map (updated by this plan)

| Doc | Role |
|-----|------|
| **This doc** | Sprint plan + engineering backlog + exit checklist |
| [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) | Human-gated items with owners |
| [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md) | North star phases + gates |
| [ROADMAP.md](../ROADMAP.md) | Product scorecard + historical milestones |
| [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md) | k6 runs + calibration results |
| [PP_4_STAGING_AUDIT.md](./PP_4_STAGING_AUDIT.md) | Staging pipeline compliance |
| [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) | DR procedures + drill log |
| [OBSERVABILITY_VENDOR_SELECTION.md](./OBSERVABILITY_VENDOR_SELECTION.md) | Vendor pick for 0.1–0.2 |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-05-30 | Initial plan: Phase 2 done; Phase 0 remediation sequenced in 4 sprints; Run 4 tracks; Enclii gaps registry |
