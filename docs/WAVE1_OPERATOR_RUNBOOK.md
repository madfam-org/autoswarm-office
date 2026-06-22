# Wave 1 Operator Runbook — Operational Proof

> **Status:** Active (2026-06-22)
> **Parent:** [FULL_REMEDIATION_PLAN_2026-06-22.md](./FULL_REMEDIATION_PLAN_2026-06-22.md) Wave 1
> **Owner:** MADFAM platform operator + Selva engineering

Wave 1 closes Phase 0 gates **0.1–0.5**: observability, load calibration evidence,
and DR proof. Engineering ships scripts; operator provisions vendors and runs them.

---

## Prerequisites

- `kubectl` access to `selva-staging` (and `selva` for prod parity)
- Grafana Cloud stack (or chosen OTel backend) — see
  [OBSERVABILITY_VENDOR_SELECTION.md](./OBSERVABILITY_VENDOR_SELECTION.md)
- Sentry Team plan + 6 project DSNs
- `STAGING_WORKER_API_TOKEN` (from `selva-staging-secrets`) for trace/Sentry probes
- Optional: Grafana read-only token for automated trace verification

---

## Step 1 — Bootstrap observability secrets (staging)

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT='https://otlp-gateway-<region>.grafana.net/otlp'
export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Basic <base64(instance:token)>'
export SENTRY_DSN_NEXUS_API='https://<key>@o<org>.ingest.de.sentry.io/<project>'
# optional: SENTRY_DSN_WORKERS, SENTRY_DSN_GATEWAY, SENTRY_DSN_COLYSEUS,
#           SENTRY_DSN_OFFICE_UI, SENTRY_DSN_ADMIN

./scripts/bootstrap-staging-observability.sh --dry-run
./scripts/bootstrap-staging-observability.sh
./scripts/verify-staging-observability.sh --require-secret --check-all
```

Repeat for production:

```bash
./scripts/bootstrap-prod-observability.sh
./scripts/verify-prod-observability.sh --require-secret --check-all
```

---

## Step 2 — OTel end-to-end trace

```bash
# Soft (secret + dispatch probe only)
./scripts/verify-observability-trace.sh

# Hard (requires Tempo/Grafana query API)
GRAFANA_URL=https://<stack>.grafana.net \
GRAFANA_TEMPO_DATASOURCE_UID=<uid> \
GRAFANA_API_TOKEN=<read-only-token> \
  ./scripts/verify-observability-trace.sh --require-trace
```

Archive the emitted `TRACE_ID` and Grafana screenshot in operator evidence.

---

## Step 3 — Sentry synthetic capture

After nexus-api deploy with Wave 1 `sentry-probe` endpoint:

```bash
export STAGING_WORKER_API_TOKEN='...'
./scripts/verify-sentry-capture.sh --staging --require-capture
```

Confirm **Issues → selva-nexus-api → `selva sentry-probe`** within 60s.

---

## Step 4 — k6 Run 4b (load calibration)

```bash
./scripts/drain-staging-task-queue.sh
kubectl apply -k infra/k8s/overlays/staging-load
./scripts/verify-staging-load-run4b-preflight.sh --require-live
./scripts/run-staging-load-calibration.sh
kubectl apply -k infra/k8s/overlays/staging   # revert
```

Record results in [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md) Run 4b row.
Hard thresholds: errors <0.5%, p99 dispatch <1500ms, DLQ <5 in 5min.

CI alternative: `.github/workflows/load-test.yml` with `calibration-dispatch.js`.

---

## Step 5 — DR backup/restore drill

```bash
./scripts/run-db-restore-drill.sh --preflight

DR_DRILL_EXECUTE=yes \
DR_SOURCE_ENV=prod \
DR_TARGET_ENV=staging-restore-sandbox \
DR_BACKUP_DATABASE_URL=postgresql://... \
DR_RESTORE_DATABASE_URL=postgresql://... \
  ./scripts/run-db-restore-drill.sh --execute

./scripts/verify-dr-drill-evidence.sh
```

Template: [docs/dr-drills/TEMPLATE.md](./dr-drills/TEMPLATE.md)

---

## Step 6 — Full Wave 1 gate bundle

```bash
# Soft run (SKIP allowed — good for first pass)
./scripts/run-wave1-gates.sh --staging

# Hard run (Phase 0 exit evidence)
PHASE0_REQUIRE_OPERATOR_GATES=true ./scripts/verify-phase0-gates.sh --staging
./scripts/run-wave1-gates.sh --staging --require-all
```

---

## Enclii adapter gaps to record

| Action | Break-glass today | Enclii follow-up |
|--------|-------------------|------------------|
| Observability secret create | `bootstrap-*-observability.sh` | Secret adapter |
| Run 4b scale overlay | `kubectl apply -k overlays/staging-load` | Load-test mode |
| DR restore target DB | `run-db-restore-drill.sh` | Sandbox DB provisioning |

---

## Exit criteria (Wave 1 complete)

- [ ] `./scripts/verify-staging-observability.sh --require-secret --check-all` → OK
- [ ] `./scripts/verify-observability-trace.sh --require-trace` → TRACE_ID found
- [ ] `./scripts/verify-sentry-capture.sh --staging --require-capture` → OK
- [ ] Run 4b row in LOAD_TEST → hard thresholds **Yes**
- [ ] `./scripts/verify-dr-drill-evidence.sh` → PASS evidence file
- [ ] Prod parity: `./scripts/verify-prod-observability.sh --require-secret --check-all`

Then proceed to [Wave 2 — Money path](./FULL_REMEDIATION_PLAN_2026-06-22.md#wave-2--money-path--controlled-promote-weeks-2-4).
