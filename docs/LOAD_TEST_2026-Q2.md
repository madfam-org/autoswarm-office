# Load Test Q2 2026 — 100 concurrent SwarmTasks calibration

> **Program Phase 0** item 0.4 / [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) Tier 3.
> Template to capture output of `tests/load/concurrent-100-swarmtasks.js` once
> staging runs the scenario. Operator: fill in Results after the run.
> See [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md).

## Why we're running this

Today's production limits are guesses, not measurements:

| Setting | Default | Source |
|---|---|---|
| `MAX_CONCURRENT_TASKS` (worker semaphore) | 3 | guessed at v0.3.0 |
| `dispatch_rate_limit` (per-user/min) | 10 | guessed at v0.3.0 |
| `TIER_DAILY_TASK_LIMIT.{starter,pro,enterprise}` | 50/200/1000 | Tulana pricing decision doc, untested under load |
| Worker pool size | 1 (per K8s deployment replica) | Helm chart default |
| Postgres pool (`DB_POOL_SIZE`) | 10 | Settings default |
| Redis Stream consumer batch size | `MAX_CONCURRENT_TASKS` | code default |

This load test puts numbers behind those defaults so the next pricing/scaling decision is data-driven.

## Scenario shape

Run from `tests/load/concurrent-100-swarmtasks.js`:

- **Stage 1**: ramp 0 → 100 concurrent VUs over 2 min (each VU dispatches a task and polls its status until completion or 60s timeout)
- **Stage 2**: hold at 100 VUs for 5 min (steady-state measurement)
- **Stage 3**: ramp down to 0 over 1 min (drain measurement)

Each VU's dispatch + 60s poll loop maintains roughly one in-flight task per VU, so 100 VUs ≈ 100 active SwarmTasks during Stage 2.

## Hard pass/fail thresholds (k6 enforces)

| Metric | Threshold | Why |
|---|---|---|
| `errors` rate | < 0.5% | Anything more is a real failure, not transient |
| `dispatch_latency_ms` p99 | < 1500ms | CSP-budget proxy; users notice slower dispatch |
| `queue_depth` max | < 30 | Above means workers are starved |
| `dlq_depth` max | < 5 in 5 min | Tasks are genuinely failing, not just queued |

Failing any of these means the run is invalid for promotion — either fix the underlying issue or adjust the scenario before producing calibration output.

## Recorded-only metrics (calibration output)

These are NOT pass/fail — they're the inputs we feed back into production config:

| Metric | What we read off it | Production setting it informs |
|---|---|---|
| `dispatch_latency_ms` p50/p95/p99 | Dispatch is the user-facing latency story | `dispatch_rate_limit` — set so p99 stays under 1500ms at projected peak load |
| `worker_in_flight` steady-state max | How many tasks were actually in-progress simultaneously | `MAX_CONCURRENT_TASKS` per worker = (steady-state / num_workers) + 20% headroom |
| Worker pool saturation % | Time at semaphore limit | If >50% of the hold window, scale up `replicas` in Helm chart |
| Postgres pool wait time p99 | DB connection contention | Bump `DB_POOL_SIZE` if pool waits show up consistently |
| Checkpoint write latency p99 (post PR #123) | PostgresSaver INSERT cost | Tune `min_size`/`max_size` of the per-worker connection pool |
| LLM provider 429 rate | Rate-limit hits per provider | Inform the per-tier daily limits — if pro tier hits 429 at the projected load, the limit needs to come down |

## Operator runbook

Once OTel tracing lands (Phase 2 item 11), wire k6 to also export to the OTel backend so we get end-to-end traces correlated with the load.

### Pre-run

1. Ensure `staging.selva.town` is on a clean post-merge state (check `git log -1` matches the desired SHA)
2. Render-check the temporary load overlay: `./scripts/verify-staging-load-run4b-preflight.sh`
3. Apply the temporary Run 4b overlay: `kubectl apply -k infra/k8s/overlays/staging-load`
4. Verify the live cluster converged: `./scripts/verify-staging-load-run4b-preflight.sh --require-live`
5. Verify staging has the same `MAX_CONCURRENT_TASKS` / `dispatch_rate_limit` / pool sizes as production OR use staging-specific overrides documented per-run
6. Drain the queue: `./scripts/drain-staging-task-queue.sh`
7. Snapshot pre-run metrics: queue depth, DLQ depth, Postgres pool stats

### During run

8. Run calibration: `./scripts/run-staging-load-calibration.sh`
9. Watch `kubectl logs -f selva-worker -n selva-staging` for warnings
10. Tail `kubectl get pods -n selva-staging -w` for worker pod restarts (would indicate the PostgresSaver fix is needed under load — see PR #123)
11. Watch the Grafana dashboard (Phase 2 SLO work, item 16) once available

### Post-run

12. Capture k6 summary output to `docs/load-test-runs/<date>.k6.json`
13. Fill in the Results table below
14. Revert normal staging guardrails: `kubectl apply -k infra/k8s/overlays/staging`
15. Open a PR adjusting the production config based on observed values + a short justification per change

## Results

### Run 1 — 2026-05-30 (invalid — rate limits)

| Field | Value |
|---|---|
| Date | 2026-05-30 |
| Staging SHA | `dffbb9a` (pre-calibration patches) |
| Operator | autonomous ops agent |
| `MAX_CONCURRENT_TASKS` at run | 3 (worker default) |
| `dispatch_rate_limit` at run | 500 (live patch) |
| `RATE_LIMIT_PER_MINUTE` at run | 60 (default) |
| Worker pod replicas | 1 |
| **Hard thresholds passed?** | **No — invalid run** |
| `dispatch_latency_ms` p50 / p95 / p99 | 201ms / 913ms / 1.7s |
| `queue_depth` p50 / max | 0 / 0 |
| `dlq_depth` final | 0 |
| `worker_in_flight` steady-state max | 0 |
| Notes | Global IP rate limit (60/min) caused 99.92% dispatch failures; k6 loop exited early (~376ms/iter). Do not use for calibration. See `docs/load-test-runs/20260530T212109Z.k6.json`. |

### Run 2 — 2026-05-30 (calibration — thresholds failed, data usable)

| Field | Value |
|---|---|
| Date | 2026-05-30 |
| Staging SHA | `dffbb9a` + live patches (`DISPATCH_RATE_LIMIT=500`, `RATE_LIMIT_PER_MINUTE=10000`, Redis `selva:tier:madfam=100000`) |
| Operator | autonomous ops agent |
| `MAX_CONCURRENT_TASKS` at run | 3 (default) |
| `dispatch_rate_limit` at run | 500 |
| `RATE_LIMIT_PER_MINUTE` at run | 10000 |
| Worker pod replicas | 1 |
| **Hard thresholds passed?** | **No** (p99 dispatch 5.03s; errors 21.77%) |
| `dispatch_latency_ms` p50 / p95 / p99 | 825ms / 5s / 5.03s |
| `queue_depth` p50 / max | 0 / 0 |
| `dlq_depth` final | 0 |
| `worker_in_flight` steady-state max | 0 (metric not surfaced — `/metrics/dashboard` gap) |
| Postgres pool wait p99 (sidecar query) | not measured |
| LLM 429 rate per provider | not measured (research graph; staging LLM optional) |
| **Recommended `MAX_CONCURRENT_TASKS` change** | Raise worker to **10–15** per pod before re-run; 3 cannot drain 100 VU inventory |
| **Recommended `dispatch_rate_limit` change** | Keep **500** on staging during calibration; prod stays 10 until Run 3 passes |
| **Recommended `TIER_DAILY_TASK_LIMIT` changes** | Use dedicated load-test org or Redis tier cache bump (script now sets 100k for 24h) |
| Notes | 654/836 dispatches 2xx (78%); poll timeouts under load; post-run queue pending ~681. Staging overlay patches in `infra/k8s/overlays/staging/patch-nexus-api.yaml`. Raw: `docs/load-test-runs/20260530T213124Z.k6.json`. |

### Run 3 — 2026-05-30 (MAX_CONCURRENT_TASKS=15, clean queue — thresholds failed)

| Field | Value |
|---|---|
| Date | 2026-05-30 |
| Staging SHA | `ad7394c` + live patches |
| Operator | autonomous ops agent |
| `MAX_CONCURRENT_TASKS` at run | **15** (worker live patch + kustomize) |
| `dispatch_rate_limit` at run | 500 |
| `RATE_LIMIT_PER_MINUTE` at run | 10000 |
| Worker pod replicas | 1 (RWO PVC — cannot scale horizontally on staging) |
| **Hard thresholds passed?** | **No** (errors 55.77%; p99 dispatch 5.06s = k6 5s POST timeout) |
| `dispatch_latency_ms` p50 / p95 / p99 | 5s / 5s / 5.06s (median pinned at client timeout) |
| `queue_depth` p50 / max | 0 / 0 (health gauge; stream backlog not reflected) |
| `dlq_depth` final | 0 |
| **Recommended next step** | Add **`passthrough`/`literal` no-LLM graph** for calibration OR scale **nexus-api** replicas on staging; single API replica saturates before workers at 100 VU |
| Notes | 582/1316 dispatches 2xx (44%). Pre-run `./scripts/drain-staging-task-queue.sh` cleared stream. Campaign loop re-verified green post-run. Raw: `docs/load-test-runs/20260530T215200Z.k6.json`. |

### Run 4 — 2026-05-30 (calibration graph + pipeline fixes — thresholds failed)

| Field | Value |
|---|---|
| Date | 2026-05-30 |
| Staging SHA | `2cb7a7a` (calibration graph + queue-stats + events RLS + workers `NEXUS_API_URL`) |
| Operator | autonomous ops agent |
| `MAX_CONCURRENT_TASKS` at run | 15 |
| `dispatch_rate_limit` at run | 500 |
| `RATE_LIMIT_PER_MINUTE` at run | 10000 |
| Worker pod replicas | 1 (RWO PVC) |
| nexus-api replicas | **1** (kustomize targets 2; Argo/live cluster stayed at 1 during run) |
| Graph type | **`calibration`** (no-LLM) |
| **Hard thresholds passed?** | **No** (errors 19.08%; p99 dispatch 10s; queue_depth max 1209) |
| `dispatch_latency_ms` p50 / p95 / p99 | 4.61s / 10s / 10s (client POST timeout) |
| `queue_depth` p50 / max | 816 / **1209** (health gauge; stream backlog visible) |
| `dlq_depth` final | 0 |
| `worker_in_flight` steady-state max | 0 (DB gauge under-counts vs stream; follow-up) |
| Dispatches 2xx | **1064/1315 (80.9%)** — up from 44% (Run 3) and 78% (Run 2) |
| **Blockers fixed this run** | (1) `graph_type=calibration` on dispatch API, (2) workers `NEXUS_API_URL` → staging svc, (3) `POST /events` RLS via `tenant_session` |
| **Recommended next step** | Run **4b**: enforce `nexus-api` replicas=2 on staging (Argo sync), re-run `./scripts/run-staging-load-calibration.sh` |
| Notes | Probe task completes in ~1s post-fix. CI smoke flakes on Cloudflare 525/502 during rollouts. Raw: `docs/load-test-runs/20260530T223724Z.k6.json`. |

### Run 4b — TBD (nexus-api scale=2, re-calibrate)

| Field | Value |
|---|---|
| Date | TBD |
| nexus-api replicas | 2 (required via `infra/k8s/overlays/staging-load`) |
| **Hard thresholds passed?** | TBD |
| Notes | Required sequence: render preflight → apply `staging-load` overlay → live preflight → drain queue → `./scripts/run-staging-load-calibration.sh` → revert normal staging overlay. |

### Run 5 — TBD (post-recommendation, validate prod config)

## Cadence

Re-run quarterly OR when any of these change materially:
- Worker semaphore size
- Pricing tier limits
- Worker pod replica count
- LLM provider mix
- A graph type's typical duration shifts >2x

Re-runs go in their own subsection above so we keep the calibration history.

## Related work

- Phase 2 item 11 (OTel exporter) — when wired, k6 should export to the same backend
- Phase 2 item 12 (Sentry) — capture worker errors observed during runs
- Phase 3 item 16 (SLO dashboards) — the Grafana board this run should appear on
- PR #123 (PostgresSaver real impl) — the worker-restart-survival mechanism whose checkpoint-write latency this run measures
