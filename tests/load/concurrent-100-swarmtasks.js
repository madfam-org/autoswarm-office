/**
 * Phase 3 calibration scenario: 100 concurrent SwarmTasks.
 *
 * Goal — calibrate the production limits we currently guess at:
 *   - MAX_CONCURRENT_TASKS (worker semaphore size, default 3)
 *   - dispatch_rate_limit (per-user dispatch sliding window)
 *   - TIER_DAILY_TASK_LIMIT (Dhanam tier per-day quota)
 *
 * Scenario shape:
 *   - Ramp to 100 active SwarmTasks "in flight" (queued + running)
 *   - Hold at 100 for 5 minutes — measure steady-state behaviour
 *   - Ramp down + measure drain time
 *
 * Differs from `task-queue-throughput.js` (which sustains 100 dispatches
 * per minute over 3 min — peak ~5 active tasks at any moment) by
 * targeting INVENTORY (concurrent active) instead of THROUGHPUT
 * (rate). They measure different things; both are needed.
 *
 * What we measure (k6 + sidecar /api/v1/health/* polling):
 *   1. dispatch_p99 — POST /swarms/dispatch latency at the 99th
 *      percentile during the 100-active hold. Threshold <1500ms (current
 *      production CSP-budget proxy).
 *   2. queue_depth — selva:task-stream pending entries via
 *      /api/v1/health/queue-stats. Threshold <30 — above that, workers
 *      are starved.
 *   3. dlq_depth — selva:task-dlq via /api/v1/health/dlq-stats.
 *      Threshold <5 — anything more in 5 min means tasks are
 *      genuinely failing, not just queued.
 *   4. worker_pool_saturation — proxy via in_flight_tasks /
 *      MAX_CONCURRENT_TASKS, derived from the metrics endpoint. We
 *      record but don't threshold — the calibration output is the
 *      observed steady-state value.
 *   5. checkpoint_write_p99 — once PostgresSaver lands (PR #123),
 *      checkpoint table commit latency. Sidecar query against
 *      pg_stat_statements optional.
 *   6. error_rate — overall HTTP error rate. Threshold <0.5%.
 *
 * Usage:
 *   k6 run -e BASE_URL=http://staging-api.selva.town \
 *          -e AUTH_TOKEN=<staging-token> \
 *          tests/load/concurrent-100-swarmtasks.js
 *
 * Output:
 *   k6 prints a final summary; pipe through `jq` if `--out json=foo.json`.
 *   Calibration values land in docs/LOAD_TEST_2026-Q2.md (template
 *   alongside this file) once staging runs the scenario for real.
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Gauge, Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:4300";
const TOKEN = __ENV.AUTH_TOKEN || "dev-token";
const TENANT_ORG = __ENV.TENANT_ORG || "";

const dispatchLatency = new Trend("dispatch_latency_ms", true);
const queueDepth = new Gauge("queue_depth");
const dlqDepth = new Gauge("dlq_depth");
const workerInFlight = new Gauge("worker_in_flight");
const errors = new Rate("errors");

const headers = {
  "Content-Type": "application/json",
  Authorization: `Bearer ${TOKEN}`,
};
if (TENANT_ORG) {
  headers["X-Selva-Tenant-Org"] = TENANT_ORG;
}

export const options = {
  scenarios: {
    // Stage 1: ramp from 0 → 100 concurrent VUs over 2 min
    // Stage 2: hold at 100 for 5 min (the steady-state measurement)
    // Stage 3: ramp down to 0 over 1 min (drain measurement)
    concurrent_swarmtasks: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "2m", target: 100 },
        { duration: "5m", target: 100 },
        { duration: "1m", target: 0 },
      ],
      gracefulRampDown: "30s",
    },
  },
  thresholds: {
    // Hard bars — failing any of these means the config is wrong
    // and we should NOT promote whatever current values produced
    // the run.
    "errors": ["rate<0.005"],
    "dispatch_latency_ms": ["p(99)<1500"],
    "queue_depth": ["value<30"],
    "dlq_depth": ["value<5"],
    // Recorded but not enforced — calibration output, not pass/fail.
    "worker_in_flight": [],
  },
};

/**
 * Each VU loops dispatch → wait → poll status. The wait time is
 * tuned so 100 VUs maintain ~100 active tasks (each VU "holds" one
 * task in queue + one in-progress on average).
 */
export default function () {
  // 1. Dispatch a task. Description is unique-per-VU so dedup
  //    middleware doesn't collapse them.
  const taskBody = JSON.stringify({
    description: `load-test-${__VU}-${Date.now()}`,
    graph_type: "research",  // No external API — keeps the test self-contained
    payload: { test: true },
  });

  const dispatchStart = Date.now();
  const dispatchRes = http.post(
    `${BASE_URL}/api/v1/swarms/dispatch`,
    taskBody,
    { headers, timeout: "5s" }
  );
  dispatchLatency.add(Date.now() - dispatchStart);

  const ok = check(dispatchRes, {
    "dispatch is 2xx": (r) => r.status >= 200 && r.status < 300,
  });
  errors.add(!ok);
  if (!ok) return;

  let taskId;
  try {
    taskId = dispatchRes.json("id");
  } catch (e) {
    errors.add(true);
    return;
  }

  // 2. Poll task status every 2s until completion or 60s timeout.
  //    This is what holds the "active task" inventory at ~100.
  const pollDeadline = Date.now() + 60000;
  while (Date.now() < pollDeadline) {
    sleep(2);
    const statusRes = http.get(
      `${BASE_URL}/api/v1/swarms/tasks/${taskId}`,
      { headers, timeout: "3s" }
    );
    if (statusRes.status >= 200 && statusRes.status < 300) {
      let status;
      try {
        status = statusRes.json("status");
      } catch (e) {
        continue;
      }
      if (status === "completed" || status === "failed") {
        break;
      }
    }
  }

  // 3. Sample queue depth + DLQ depth + worker in-flight every 5s
  //    from one VU only (avoids polling-storm artifacts in the metric).
  if (__VU === 1) {
    const qres = http.get(
      `${BASE_URL}/api/v1/health/queue-stats`,
      { headers, timeout: "3s" }
    );
    if (qres.status === 200) {
      try {
        const stats = qres.json();
        queueDepth.add(stats.queue_depth ?? stats.stream_length ?? 0);
        if (stats.worker_in_flight !== undefined) {
          workerInFlight.add(stats.worker_in_flight);
        }
      } catch (e) {
        // ignore parse error
      }
    }

    const dres = http.get(
      `${BASE_URL}/api/v1/health/dlq-stats`,
      { headers, timeout: "3s" }
    );
    if (dres.status === 200) {
      try {
        const stats = dres.json();
        dlqDepth.add(stats.depth ?? stats.dlq_depth ?? 0);
      } catch (e) {
        // ignore
      }
    }
  }
}

/**
 * After the test, k6 prints summary metrics. The values that matter
 * for calibration:
 *
 *   dispatch_latency_ms p(50), p(95), p(99) — set
 *     dispatch_rate_limit so p(99) stays under threshold.
 *
 *   queue_depth max — if this hit 30+ during the hold phase,
 *     either bump MAX_CONCURRENT_TASKS or accept slower drain.
 *
 *   dlq_depth max — must be near-zero. Anything else means tasks
 *     are genuinely failing, not just slow.
 *
 *   worker_in_flight max — observed steady state. Use this to
 *     pick MAX_CONCURRENT_TASKS for prod = (this value / num_workers)
 *     + headroom.
 *
 * Record the values in docs/LOAD_TEST_2026-Q2.md alongside the
 * k6 summary output.
 */
