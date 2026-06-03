#!/usr/bin/env bash
# Run full k6 100-concurrent SwarmTasks calibration against staging (ROI Tier 3 #5).
#
# Preflight: worker token, optional queue drain, warns if dispatch rate limit is low.
# Requires staging DISPATCH_RATE_LIMIT high enough for shared worker sub (default patch: 500).
#
# Usage:
#   ./scripts/run-staging-load-full.sh
#   ./scripts/run-staging-load-full.sh --skip-drain
#   AUTH_TOKEN=<jwt> TENANT_ORG=madfam ./scripts/run-staging-load-full.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
TOKEN="${AUTH_TOKEN:-${STAGING_LOAD_TEST_TOKEN:-${STAGING_CAMPAIGN_TEST_TOKEN:-}}}"
TENANT_ORG="${STAGING_TENANT_ORG:-madfam}"
SKIP_DRAIN=false
OUT_DIR="${ROOT}/docs/load-test-runs"
K6_SCRIPT="concurrent-100-swarmtasks.js"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-drain) SKIP_DRAIN=true; shift ;;
    --script)
      K6_SCRIPT="${2:?--script requires a filename}"
      shift 2
      ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$TOKEN" ]] && command -v kubectl >/dev/null 2>&1; then
  TOKEN="$(kubectl -n selva-staging get secret selva-staging-secrets \
    -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
  if [[ -n "$TOKEN" ]]; then
    echo "Using WORKER_API_TOKEN from selva-staging-secrets (org=${TENANT_ORG})"
  fi
fi

if [[ -z "$TOKEN" ]]; then
  echo "FAIL: set AUTH_TOKEN or ensure kubectl can read WORKER_API_TOKEN"
  exit 1
fi

if ! command -v k6 >/dev/null 2>&1; then
  echo "FAIL: k6 not installed — brew install k6 or use .github/workflows/load-test.yml"
  exit 1
fi

HDR_AUTH=(-H "Authorization: Bearer ${TOKEN}")
HDR_TENANT=()
if [[ -n "$TENANT_ORG" ]]; then
  HDR_TENANT=(-H "X-Selva-Tenant-Org: ${TENANT_ORG}")
fi

echo "== Staging load calibration preflight (${BASE_URL}) =="

if command -v kubectl >/dev/null 2>&1; then
  LIMIT="$(kubectl -n selva-staging get deploy nexus-api \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DISPATCH_RATE_LIMIT")].value}' 2>/dev/null || true)"
  if [[ -z "$LIMIT" || "$LIMIT" -lt 120 ]]; then
    echo "WARN: DISPATCH_RATE_LIMIT=${LIMIT:-10(default)} — worker token shares sub service:worker"
    echo "      Bump via infra/k8s/overlays/staging/patch-nexus-api.yaml (recommended: 500) before a valid 100-VU run"
  else
    echo "OK: DISPATCH_RATE_LIMIT=${LIMIT}"
  fi
  IP_LIMIT="$(kubectl -n selva-staging get deploy nexus-api \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="RATE_LIMIT_PER_MINUTE")].value}' 2>/dev/null || true)"
  if [[ -z "$IP_LIMIT" || "$IP_LIMIT" -lt 1000 ]]; then
    echo "WARN: RATE_LIMIT_PER_MINUTE=${IP_LIMIT:-60(default)} — k6 egress is one IP; bump to 10000 for calibration"
  else
    echo "OK: RATE_LIMIT_PER_MINUTE=${IP_LIMIT}"
  fi
fi

if ! $SKIP_DRAIN; then
  echo "--- drain staging queue (Redis + open tasks) ---"
  "${ROOT}/scripts/drain-staging-task-queue.sh" || echo "WARN: queue drain failed — results may be skewed"
fi

if [[ -n "$TENANT_ORG" ]] && command -v kubectl >/dev/null 2>&1; then
  echo "--- staging load-test budget headroom (Redis tier cache) ---"
  kubectl -n selva-staging exec deploy/nexus-api -- python3 -c "
import asyncio, os
from selva_redis_pool import get_redis_pool
async def main():
    pool = get_redis_pool(url=os.environ['REDIS_URL'])
    await pool.execute_with_retry('set', 'selva:tier:${TENANT_ORG}', '100000', ex=86400)
asyncio.run(main())
" >/dev/null 2>&1 && echo "OK: selva:tier:${TENANT_ORG}=100000 (24h TTL)"
fi

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_JSON="${OUT_DIR}/${STAMP}.k6.json"

echo "--- k6 ${K6_SCRIPT} (~8 min) ---"
echo "    results → ${OUT_JSON}"
echo "    fill docs/LOAD_TEST_2026-Q2.md after completion"

exec k6 run \
  --out "json=${OUT_JSON}" \
  -e "BASE_URL=${BASE_URL}" \
  -e "AUTH_TOKEN=${TOKEN}" \
  -e "TENANT_ORG=${TENANT_ORG}" \
  "${ROOT}/tests/load/${K6_SCRIPT}"
