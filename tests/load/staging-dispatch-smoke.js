/**
 * Short staging dispatch smoke — validates auth + dispatch path without
 * tripping DISPATCH_RATE_LIMIT (default 10 req/60s per caller).
 *
 * Usage:
 *   k6 run -e BASE_URL=https://staging-api.selva.town \
 *          -e AUTH_TOKEN=<token> \
 *          -e TENANT_ORG=madfam \
 *          tests/load/staging-dispatch-smoke.js
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:4300";
const TOKEN = __ENV.AUTH_TOKEN || "dev-token";
const TENANT_ORG = __ENV.TENANT_ORG || "";
const DISPATCH_PAUSE_SECONDS = Number(__ENV.DISPATCH_PAUSE_SECONDS || "8");

const dispatchLatency = new Trend("dispatch_latency_ms", true);
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
    dispatch_smoke: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 5,
      maxDuration: "2m",
    },
  },
  thresholds: {
    errors: ["rate<0.01"],
    dispatch_latency_ms: ["p(99)<3000"],
  },
};

export default function () {
  const body = JSON.stringify({
    description: `staging-smoke-${__ITER}-${Date.now()}`,
    graph_type: "research",
    payload: { test: true, smoke: true },
  });

  const start = Date.now();
  const res = http.post(`${BASE_URL}/api/v1/swarms/dispatch`, body, {
    headers,
    timeout: "10s",
  });
  dispatchLatency.add(Date.now() - start);

  const ok = check(res, {
    "dispatch 2xx": (r) => r.status >= 200 && r.status < 300,
  });
  errors.add(!ok);
  sleep(DISPATCH_PAUSE_SECONDS);
}
