# Service-Level Objectives (SLOs)

> Phase 3 item 16 in the [full-remediation plan](../ROADMAP.md). Defines the
> per-endpoint latency / error / availability targets we hold ourselves
> to in production, the error budget that follows, and the alert burn
> rates that page on-call.
>
> **Status**: definition phase. SLI dashboards land once OTel is wired
> (Program Phase 0 / [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) item 1)
> and Sentry DSNs flow (item 2). On-call alert wiring lands as a follow-up PR.
> See [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md).

---

## 1. Service tier classification

Each endpoint class gets one of three tiers. The tier dictates the
SLO numbers, error budget, and alert burn-rate.

| Tier | Examples | User-perceived impact of breach |
|---|---|---|
| **Tier 1 — User-blocking** | `/swarms/dispatch`, `/auth/*`, `/onboarding/*`, `/approvals/*` (POST/approve/deny), `/chat/messages` POST, WS upgrade | User can't perform the core action they came here to do |
| **Tier 2 — Feature-degrading** | `/marketplace/*` (publish/install), `/calendar/*`, `/maps/*`, `/workflows/*` mutations, `/voice/transcribe`, `/billing/*` | A feature breaks; user can do other things |
| **Tier 3 — Background / cosmetic** | `/agents/*/stats` PATCH, `/health/*`, `/metrics/*`, `/events` GET pagination beyond first page | Internal callers notice; users don't |

---

## 2. Latency SLOs

Targets are **30-day rolling p99**. Per-endpoint p50 / p95 / p99 dashboards
land with the SLI work (Phase 2 OTel + Grafana).

| Tier | p50 target | p95 target | p99 target |
|---|---|---|---|
| Tier 1 | 200 ms | 500 ms | **1500 ms** |
| Tier 2 | 500 ms | 1500 ms | 3000 ms |
| Tier 3 | 1000 ms | 5000 ms | 10000 ms |

### Why these numbers

- **Tier 1 p99 = 1500ms**: matches the existing CSP-budget proxy used
  in `tests/load/concurrent-100-swarmtasks.js`. A user clicking
  "Dispatch" who waits >1.5s starts to question whether the click
  registered.
- **Tier 2 p99 = 3000ms**: marketplace install / calendar fetch are
  background-feeling actions; users tolerate up to ~3s before
  perceiving the page as broken.
- **Tier 3 p99 = 10s**: stats PATCH happens after every task
  completion in fire-and-forget fashion; nobody sees it.

### Excluded from latency SLOs

Latency SLOs explicitly **do not cover** WebSocket upgrade (those have
their own connection-establishment SLO below) and inference proxy
routes that depend on third-party LLM provider latency (Anthropic /
OpenAI). For those:

| Endpoint class | SLI | Target |
|---|---|---|
| WS upgrade | Time to first message after `Sec-WebSocket-Accept` | p99 < 2s |
| `/v1/chat/completions` (inference proxy) | First-token-latency p99 | < 8s (informational; bound by upstream) |

---

## 3. Availability / error-rate SLOs

Targets are **30-day rolling**.

| Tier | Availability target | Error budget per 30d |
|---|---|---|
| Tier 1 | 99.9% | 43.2 minutes |
| Tier 2 | 99.5% | 3 hours 36 minutes |
| Tier 3 | 99.0% | 7 hours 12 minutes |

### What counts as an error

- Any HTTP 5xx response
- Any HTTP 4xx response that is NOT one of: 400 (client error), 401, 403, 404, 409, 410, 422 (Pydantic validation), 429 (rate limit)
- WebSocket connection rejections that are NOT 4401 (auth) or 4403 (permission) per-our-protocol close codes
- Stream timeouts > 30s on the response side

### What's NOT counted

- 4xx codes in the "expected" set above (client error, not service error)
- Tasks that complete with `status: "failed"` because the LLM raised — that's a **task-level** SLI, not a request-level one. Tracked separately in §6.

---

## 4. Per-endpoint SLI specifications

Concrete query-able specs the OTel/Grafana work will translate into
recording rules. Tier classification + the §2/§3 numbers determine the
target.

| Endpoint | Tier | Method | SLI: success | SLI: latency |
|---|---|---|---|---|
| `/api/v1/auth/*` | 1 | * | non-5xx, non-4xx-not-in-expected | p99 < 1500ms |
| `/api/v1/onboarding/*` | 1 | POST/PUT/PATCH | as above | p99 < 1500ms |
| `/api/v1/swarms/dispatch` | 1 | POST | as above + dispatched task ID returned | p99 < 1500ms |
| `/api/v1/swarms/tasks/{id}` | 2 | GET | as above | p99 < 3000ms |
| `/api/v1/approvals/{id}/approve` | 1 | POST | as above + state transition succeeded | p99 < 1500ms |
| `/api/v1/approvals/{id}/deny` | 1 | POST | as above + state transition succeeded | p99 < 1500ms |
| `/api/v1/chat/messages` | 1 | POST | as above + message persisted | p99 < 1500ms |
| `/api/v1/marketplace/skills` | 2 | POST | as above | p99 < 3000ms |
| `/api/v1/marketplace/skills/{id}/install` | 2 | POST | as above + skill files written | p99 < 3000ms |
| `/api/v1/calendar/connect` | 2 | POST | as above + OAuth token stored | p99 < 3000ms |
| `/api/v1/calendar/events` | 2 | GET | as above | p99 < 3000ms |
| `/api/v1/maps/*` | 2 | mutations | as above | p99 < 3000ms |
| `/api/v1/workflows/*` | 2 | mutations | as above | p99 < 3000ms |
| `/api/v1/voice/transcribe` | 2 | POST | as above + transcript returned | p99 < 8000ms (audio length dependent) |
| `/api/v1/agents/{id}/stats` | 3 | PATCH | non-5xx | p99 < 10000ms |
| `/api/v1/health/*` | 3 | GET | non-5xx | p99 < 1000ms (tighter — these gate K8s liveness) |
| `/api/v1/metrics/*` | 3 | GET | non-5xx | p99 < 5000ms |
| `/api/v1/events/ws` | 1 | WS upgrade | upgrade succeeded + initial batch sent | p99 first-msg < 2000ms |
| `/api/v1/approvals/ws` | 1 | WS upgrade | upgrade succeeded + initial batch sent | p99 first-msg < 2000ms |
| `/api/v1/stripe/webhook` | 1 | POST | non-5xx (Stripe retries 5xx for 3 days) | p99 < 1000ms |
| `/api/v1/gateway/{any}` | 2 | POST | non-5xx + signature-validated | p99 < 1500ms (webhooks must process fast) |

---

## 5. Burn-rate alerts

Multi-window multi-burn-rate alerting per Google SRE Workbook
chapter 5. Two alert tiers, each with two windows so we catch fast
burns and slow ones.

### Tier 1 — Page on-call

| Burn rate | Long window | Short window | Burns budget in |
|---|---|---|---|
| 14.4× | 1 hour | 5 minutes | ~2 hours |
| 6× | 6 hours | 30 minutes | ~5 hours |

These page on-call to PagerDuty. They mean Tier 1 SLO is at risk of
exhausting the 30-day budget within hours.

### Tier 2 — Notify (Slack #ops, no page)

| Burn rate | Long window | Short window | Burns budget in |
|---|---|---|---|
| 3× | 1 day | 2 hours | ~10 days |
| 1× | 3 days | 6 hours | ~30 days (= budget exhausted) |

Tier 2 alerts indicate the budget is on track to be fully consumed
in <30 days but not imminent. Surface to ops, no page.

### Per-tier overrides

Tier 1 endpoints get Tier 1 alert thresholds.
Tier 2 endpoints get Tier 2 alert thresholds.
Tier 3 endpoints don't get burn-rate alerts at all — only basic
"site down" availability alerts via blackbox-exporter pings.

---

## 6. Task-level SLIs (separate from request-level)

A SwarmTask is an asynchronous unit that can take seconds to minutes.
Its success/latency story is independent from the HTTP request that
dispatched it.

| SLI | Target | Calculation |
|---|---|---|
| **Task success rate** (overall) | ≥ 95% over 7 days | `task.completed events / (task.completed + task.failed)` |
| **Task success rate** (per graph_type) | informational; tracked per type | as above, grouped by `graph_type` |
| **Approval queue p95 latency** | < 2 hours | time between `approval.created` and `approval.{approved,denied,expired}` |
| **DLQ depth** | < 5 sustained | continuous gauge from `/api/v1/health/dlq-stats` |
| **Bandit reward exhaustion** | informational | `update_bandit_reward` calls per agent per day — anomalies indicate model drift or workflow regression |

DLQ depth >5 is a Tier 1 alert page (something is wedging tasks
permanently). Approval queue latency >4 hours is a Tier 2 notify
(humans are slow to approve, not an outage but worth surfacing).

---

## 7. SLO review cadence

Quarterly. Every 90 days, review:

1. Did we hit each SLO's target over the last 90 days? (No → adjust
   the target down OR commit to engineering work to hit it.)
2. Were the burn-rate alerts noisy or quiet? (Tune.)
3. Did any tier 3 endpoint sustain enough load to deserve tier 2
   classification? (Reclassify.)
4. Are there NEW endpoints since last review that need SLI specs?
   (Add to §4.)

Outcome doc per quarter: `docs/SLO_REVIEW_QYYYY.md` summarizing the
above + any config or code changes the review triggered.

---

## 8. Implementation references

These items in the [full-remediation plan](../ROADMAP.md) deliver
the infrastructure these SLOs need to be measurable + actionable:

- **Phase 2 item 11 — OTel exporter wired**: produces the latency +
  error rate signal the SLOs are computed from
- **Phase 2 item 12 — Sentry per-service DSNs**: error capture for
  the request-class signal
- **Phase 3 item 16 (this doc)**: SLO definitions
- **Phase 3 item 19 (audit trail)**: TaskEvent stream is the source
  for §6 task-level SLIs
- **Phase 3 alert wiring** (follow-up PR): translates §5 burn rates
  into PagerDuty / Slack #ops routes
- **PR #128 — load test scenario**: the calibration run that
  validates Tier 1 latency thresholds are achievable under realistic
  concurrency

---

## 9. Adoption checklist

For each new endpoint added after this doc lands, the PR author MUST:

- [ ] Classify the endpoint into Tier 1 / 2 / 3 in the PR description
- [ ] Add an SLI row to §4 of this doc in the same PR
- [ ] Verify a label/attribute is exposed for OTel span queries
      (e.g., `http.route` is set; `http.status_code` is set)
- [ ] If Tier 1, confirm the existing burn-rate alert routing covers
      the new route prefix (no special handling required if the
      route falls under `/api/v1/`)

Reviewers MUST block merge if the classification + SLI row are missing.
