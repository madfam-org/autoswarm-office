# Session log — Phase 0 Run 4 calibration (2026-05-30)

> **Scope:** ROI-priority autonomous ops on staging — unblock k6 Run 4, fix
> staging worker/API pipeline bugs, execute calibration load test, record results.
> **Head SHA at wrap:** `fab8663` on `main`.

---

## Objectives (this session)

1. Deploy Run 4 engineering (`calibration` graph, queue-stats, load scripts) to staging.
2. Execute `./scripts/run-staging-load-calibration.sh` and record in [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md).
3. Fix any blockers discovered during probe/load runs (API validation, worker URL, RLS).
4. Reconcile Dhanam webhook fan-out; verify billing + campaign gates where possible.

---

## Commits shipped (`main`)

| SHA | Summary |
|-----|---------|
| `67fc050` | Run 4 prep: calibration graph, queue-stats fields, k6 script, staging nexus-api replicas=2 in kustomize |
| `14ac709` | **fix(api):** allow `graph_type=calibration` on `DispatchRequest` |
| `9761958` | **fix(staging):** workers `NEXUS_API_URL` → `http://nexus-api.autoswarm-staging.svc.cluster.local` |
| `2cb7a7a` | **fix(api):** `POST /events` uses `tenant_session` (worker RLS on `task_events`) |
| `fab8663` | **docs:** Run 4 results in `LOAD_TEST_2026-Q2.md` |

Staging digest bumps (`deploy(staging): update digests to …`) followed each fix push via `staging-deploy.yml`.

---

## Root causes fixed

### 1. API rejected calibration dispatches

- **Symptom:** `422` — `graph_type` pattern missing `calibration`.
- **Fix:** `apps/nexus-api/nexus_api/routers/swarms.py` + test in `test_swarms_coverage.py`.

### 2. Workers PATCH/events hit prod nexus-api

- **Symptom:** Worker logs showed `http://nexus-api.autoswarm.svc.cluster.local` (prod namespace); staging tasks stayed `queued` or `running` forever.
- **Cause:** `patch-workers.yaml` overrode secrets/env but not `NEXUS_API_URL` from `autoswarm-config` ConfigMap (prod cluster-local URL).
- **Fix:** `infra/k8s/overlays/staging/patch-workers.yaml` — explicit staging URL override (same pattern as `patch-gateway.yaml`).

### 3. Worker event POST failed strict RLS

- **Symptom:** `POST /api/v1/events/` → **500** — `InsufficientPrivilegeError` on `task_events`.
- **Cause:** `create_event` declared `Depends(get_db)` before `Depends(get_current_user)`; session `app.current_org_id` was empty at insert.
- **Fix:** `apps/nexus-api/nexus_api/routers/events.py` — `tenant_session(org_id)` after auth resolves tenant.

### 4. Post-fix probe

- Events POST → **201**; calibration dispatch → **completed in ~1s** (`graph_type=calibration`).

---

## Verification matrix (end of session)

| Gate | Command | Result |
|------|---------|--------|
| Dhanam webhook reconcile | `./scripts/reconcile-dhanam-selva-webhook.sh` | **OK** (re-run when fan-out drifts) |
| Dhanam billing path | `./scripts/verify-dhanam-billing-path.sh --staging` | **OK** |
| Staging observability | `./scripts/verify-staging-observability.sh` | **SKIP** — no `autoswarm-observability-secrets` |
| Dhanam price→tier | `./scripts/verify-dhanam-price-tier-map.sh --staging` | **SKIP** — catalog not wired |
| Campaign API loop | `env -u AUTH_TOKEN ./scripts/verify-campaign-loop.sh --staging` | **OK** when API stable (CI hit transient 525 on HITL during rollouts) |
| Calibration probe | dispatch + poll `graph_type=calibration` | **OK** (~1s to `completed`) |

---

## k6 Run 4 results

**Script:** `./scripts/run-staging-load-calibration.sh`  
**Raw:** `docs/load-test-runs/20260530T223724Z.k6.json`  
**Full table:** [LOAD_TEST_2026-Q2.md § Run 4](./LOAD_TEST_2026-Q2.md)

| Metric | Value |
|--------|-------|
| Dispatches 2xx | **1064 / 1315 (80.9%)** |
| Errors rate | 19.08% (threshold &lt; 0.5%) |
| `dispatch_latency_ms` p50 / p99 | 4.61s / **10s** (client POST timeout) |
| `queue_depth` max | **1209** (threshold &lt; 30) |
| `dlq_depth` | 0 |
| `worker_in_flight` max | 0 (DB gauge; stream backlog reflected in `queue_depth`) |
| **Hard thresholds passed?** | **No** |

**Compared to Run 3 (research graph, same infra):** 44% → **80.9%** dispatch success — calibration graph and pipeline fixes are working; remaining failure is **API/worker capacity** (single `nexus-api` replica during run).

**Run 4b (next):** Enforce `nexus-api` replicas=**2** on staging (Argo/kustomize drift observed — cluster reverts to 1 without sync), drain queue, re-run same script.

---

## CI / staging deploy notes

- `staging-deploy.yml` completed image builds after each push; **smoke test flaked** twice on Cloudflare **502/525** during rollouts (Dhanam billing verify, campaign HITL approve). Manual verifiers pass when origin is stable.
- **Recommendation:** Add smoke retry/backoff or run smoke ≥60s after Argo sync (follow-up engineering).

---

## Enclii adapter gaps (new / reinforced)

| Gap | Impact | Workaround |
|-----|--------|------------|
| Staging `NEXUS_API_URL` not in Enclii overlay contract | Workers silently talked to prod API | `patch-workers.yaml` (committed) |
| `nexus-api` replica count drifts vs kustomize | Run 4 ran at 1 replica despite `replicas: 2` | `kubectl apply -k infra/k8s/overlays/staging` or Argo hard sync |
| Dhanam `PRODUCT_WEBHOOK_URLS` ExternalSecret drift | Empty fan-out | `./scripts/reconcile-dhanam-selva-webhook.sh` (idempotent) |
| Staging `DATABASE_ADMIN_URL` unset | Drain script marks 0 DB rows under strict RLS | Break-glass; provision `app_admin` on staging |

---

## Still open (ROI order)

### Tier 1 — Operator

1. Provision `autoswarm-observability-secrets` → `./scripts/bootstrap-staging-observability.sh`
2. `./scripts/verify-observability-trace.sh` once OTel live

### Tier 2 — Operator (Dhanam/Stripe)

3. Map Stripe price IDs → tiers in Dhanam catalog
4. Prod `PRODUCT_WEBHOOK_URLS` + durable fan-out (stop ExternalSecret drift)

### Tier 3 — Engineering + ops

5. **Run 4b:** `./scripts/drain-staging-task-queue.sh` → confirm `nexus-api` replicas=2 → `./scripts/run-staging-load-calibration.sh`
6. Investigate `worker_in_flight` under-count vs stream backlog (health endpoint)
7. **DR drill:** `make db-backup` → restore → [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) drill log

### Phase 1 / promote (after Phase 0 exit)

8. Revenue loop proof on staging → `promote-to-prod.yml` per [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) Sprint 2

---

## Handoff commands

```bash
# Confirm staging scale + queue
kubectl -n autoswarm-staging get deploy nexus-api workers
curl -sS https://staging-api.selva.town/api/v1/health/queue-stats | jq .

# Run 4b
./scripts/drain-staging-task-queue.sh
./scripts/run-staging-load-calibration.sh

# Gates
./scripts/verify-staging-observability.sh
./scripts/verify-dhanam-billing-path.sh --staging
env -u AUTH_TOKEN ./scripts/verify-campaign-loop.sh --staging
./scripts/reconcile-dhanam-selva-webhook.sh
```

---

## Related docs

- [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) — Sprint 1 progress
- [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) — item 5c (Run 4 / 4b)
- [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md) — Runs 1–4 + Run 4b placeholder
- [PP_4_STAGING_AUDIT.md](./PP_4_STAGING_AUDIT.md) — staging guardrails
- [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md) — Phase 0 exit checklist

---

## Agent transcript

Full tool/conversation log: Cursor agent transcript `ebe97194-e9bb-4a09-80f7-4ab5c3ec79b7`.
