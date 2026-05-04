# Load Test Q2 2026 — 100 concurrent SwarmTasks calibration

> Phase 3 item 17 in the [full-remediation plan](../ROADMAP.md). Template doc to capture the calibration output of `tests/load/concurrent-100-swarmtasks.js` once staging actually runs the scenario. Operator: fill in the Results section after the run.

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
2. Verify staging has the same `MAX_CONCURRENT_TASKS` / `dispatch_rate_limit` / pool sizes as production OR use staging-specific overrides documented per-run
3. Drain the queue: `curl -XPOST $STAGING_URL/api/v1/swarms/tasks/reap-stale` (uses the role-gated reap-stale endpoint per PR #114)
4. Snapshot pre-run metrics: queue depth, DLQ depth, Postgres pool stats

### During run

5. Watch `kubectl logs -f autoswarm-worker -n autoswarm-staging` for warnings
6. Tail `kubectl get pods -n autoswarm-staging -w` for worker pod restarts (would indicate the PostgresSaver fix is needed under load — see PR #123)
7. Watch the Grafana dashboard (Phase 2 SLO work, item 16) once available

### Post-run

8. Capture k6 summary output to `docs/load-test-runs/<date>.k6.json`
9. Fill in the Results table below
10. Open a PR adjusting the production config based on observed values + a short justification per change

## Results

### Run 1 — TBD

| Field | Value |
|---|---|
| Date | TBD |
| Staging SHA | TBD |
| Operator | TBD |
| `MAX_CONCURRENT_TASKS` at run | TBD |
| `dispatch_rate_limit` at run | TBD |
| Worker pod replicas | TBD |
| **Hard thresholds passed?** | TBD |
| `dispatch_latency_ms` p50 / p95 / p99 | TBD |
| `queue_depth` p50 / max | TBD |
| `dlq_depth` final | TBD |
| `worker_in_flight` steady-state max | TBD |
| Postgres pool wait p99 (sidecar query) | TBD |
| LLM 429 rate per provider | TBD |
| **Recommended `MAX_CONCURRENT_TASKS` change** | TBD |
| **Recommended `dispatch_rate_limit` change** | TBD |
| **Recommended `TIER_DAILY_TASK_LIMIT` changes** | TBD |
| Notes | TBD |

### Run 2 — TBD (post-recommendation, validate the change)

| Field | Value |
|---|---|
| Date | TBD |
| Same shape as Run 1 with new config | TBD |

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
