/**
 * Phase 0 Run 4 — 100 concurrent SwarmTasks using graph_type=calibration.
 *
 * Same shape as concurrent-100-swarmtasks.js but uses the no-LLM calibration
 * graph so results measure API/worker/queue limits — not LLM latency.
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Gauge, Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:4300";
const TOKEN = __ENV.AUTH_TOKEN || "dev-token";
const TENANT_ORG = __ENV.TENANT_ORG || "";
const GRAPH_TYPE = __ENV.GRAPH_TYPE || "calibration";

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
    errors: ["rate<0.005"],
    dispatch_latency_ms: ["p(99)<1500"],
    queue_depth: ["value<30"],
    dlq_depth: ["value<5"],
    worker_in_flight: [],
  },
};

function sampleQueueMetrics() {
  const qres = http.get(`${BASE_URL}/api/v1/health/queue-stats`, {
    headers,
    timeout: "3s",
  });
  if (qres.status === 200) {
    try {
      const stats = qres.json();
      queueDepth.add(stats.queue_depth ?? stats.stream_length ?? 0);
      if (stats.worker_in_flight !== undefined) {
        workerInFlight.add(stats.worker_in_flight);
      }
    } catch (e) {
      // ignore
    }
  }

  const dres = http.get(`${BASE_URL}/api/v1/health/dlq-stats`, {
    headers,
    timeout: "3s",
  });
  if (dres.status === 200) {
    try {
      const stats = dres.json();
      dlqDepth.add(stats.depth ?? stats.dlq_depth ?? 0);
    } catch (e) {
      // ignore
    }
  }
}

export default function () {
  const taskBody = JSON.stringify({
    description: `calibration-${__VU}-${Date.now()}`,
    graph_type: GRAPH_TYPE,
    payload: { test: true, calibration: true },
  });

  const dispatchStart = Date.now();
  const dispatchRes = http.post(
    `${BASE_URL}/api/v1/swarms/dispatch`,
    taskBody,
    { headers, timeout: "10s" }
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

  const pollDeadline = Date.now() + 30000;
  while (Date.now() < pollDeadline) {
    sleep(1);
    const statusRes = http.get(`${BASE_URL}/api/v1/swarms/tasks/${taskId}`, {
      headers,
      timeout: "3s",
    });
    if (statusRes.status >= 200 && statusRes.status < 300) {
      try {
        const status = statusRes.json("status");
        if (status === "completed" || status === "failed") {
          break;
        }
      } catch (e) {
        continue;
      }
    }
  }

  if (__VU === 1) {
    sampleQueueMetrics();
  }
}
