#!/usr/bin/env bash
# Verify Phase 0 Run 4b staging load-test prerequisites.
#
# Default mode validates the rendered staging-load overlay. With --require-live,
# it also checks the live staging cluster has converged before k6 runs.
#
# Usage:
#   ./scripts/verify-staging-load-run4b-preflight.sh
#   ./scripts/verify-staging-load-run4b-preflight.sh --require-live
#   RUN4B_NEXUS_API_REPLICAS=2 ./scripts/verify-staging-load-run4b-preflight.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OVERLAY="${RUN4B_OVERLAY:-infra/k8s/overlays/staging-load}"
NS="${STAGING_NAMESPACE:-selva-staging}"
EXPECTED_NEXUS_REPLICAS="${RUN4B_NEXUS_API_REPLICAS:-2}"
MIN_DISPATCH_RATE="${RUN4B_MIN_DISPATCH_RATE_LIMIT:-500}"
MIN_IP_RATE="${RUN4B_MIN_RATE_LIMIT_PER_MINUTE:-10000}"
MIN_WORKER_CONCURRENCY="${RUN4B_MIN_WORKER_CONCURRENCY:-15}"
REQUIRE_LIVE=false

usage() {
  awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"
}

for arg in "$@"; do
  case "$arg" in
    --require-live)
      REQUIRE_LIVE=true
      ;;
    --namespace=*)
      NS="${arg#*=}"
      ;;
    --overlay=*)
      OVERLAY="${arg#*=}"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "FAIL: unknown argument: $arg"
      exit 2
      ;;
  esac
done

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

require_int_ge() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ ! "$actual" =~ ^[0-9]+$ ]]; then
    fail "${label} is not numeric: ${actual:-<empty>}"
  fi
  if (( actual < expected )); then
    fail "${label}=${actual}; expected >= ${expected}"
  fi
  pass "${label}=${actual}"
}

require_int_eq() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ ! "$actual" =~ ^[0-9]+$ ]]; then
    fail "${label} is not numeric: ${actual:-<empty>}"
  fi
  if (( actual != expected )); then
    fail "${label}=${actual}; expected ${expected}"
  fi
  pass "${label}=${actual}"
}

if ! command -v kubectl >/dev/null 2>&1; then
  fail "kubectl unavailable; cannot render ${OVERLAY}"
fi

MANIFEST="$(mktemp -t selva-run4b-manifest.XXXXXX.yaml)"
trap 'rm -f "$MANIFEST"' EXIT

echo "== Run 4b rendered preflight (${OVERLAY}) =="
kubectl kustomize "$OVERLAY" > "$MANIFEST"

python3 - "$MANIFEST" "$EXPECTED_NEXUS_REPLICAS" "$MIN_DISPATCH_RATE" "$MIN_IP_RATE" "$MIN_WORKER_CONCURRENCY" <<'PY'
import re
import sys
from pathlib import Path

manifest = Path(sys.argv[1]).read_text()
expected_replicas = int(sys.argv[2])
min_dispatch = int(sys.argv[3])
min_ip = int(sys.argv[4])
min_worker = int(sys.argv[5])

def metadata_name(doc: str) -> str:
    match = re.search(r"(?ms)^metadata:\n(?P<body>(?:^  .*\n?)+)", doc)
    if not match:
        return ""
    name = re.search(r"(?m)^  name:\s*([^\n]+)", match.group("body"))
    return name.group(1).strip().strip('"') if name else ""

docs = [doc.strip() for doc in re.split(r"(?m)^---\s*$", manifest) if doc.strip()]

def find_doc(kind: str, name: str) -> str:
    for doc in docs:
        if re.search(rf"(?m)^kind:\s*{re.escape(kind)}\s*$", doc) and metadata_name(doc) == name:
            return doc
    raise SystemExit(f"FAIL: rendered {kind}/{name} not found")

def scalar(doc: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*\"?([^\"\n]+)\"?\s*$", doc)
    return match.group(1).strip() if match else ""

def env_value(doc: str, env_name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*-\s+name:\s*{re.escape(env_name)}\s*\n\s*value:\s*\"?([^\"\n]+)\"?",
        doc,
    )
    return match.group(1).strip() if match else ""

def require_int(label: str, raw: str, expected: int, *, eq: bool = False) -> None:
    if not raw.isdigit():
        raise SystemExit(f"FAIL: rendered {label} is not numeric: {raw or '<empty>'}")
    actual = int(raw)
    if eq and actual != expected:
        raise SystemExit(f"FAIL: rendered {label}={actual}; expected {expected}")
    if not eq and actual < expected:
        raise SystemExit(f"FAIL: rendered {label}={actual}; expected >= {expected}")
    op = "=" if eq else ">="
    print(f"OK: rendered {label}={actual} ({op} {expected})")

nexus = find_doc("Deployment", "nexus-api")
workers = find_doc("Deployment", "workers")
hpa = find_doc("HorizontalPodAutoscaler", "nexus-api-hpa")

require_int("nexus-api replicas", scalar(nexus, "replicas"), expected_replicas, eq=True)
require_int("nexus-api-hpa minReplicas", scalar(hpa, "minReplicas"), expected_replicas, eq=True)
require_int("nexus-api-hpa maxReplicas", scalar(hpa, "maxReplicas"), expected_replicas, eq=True)
require_int("DISPATCH_RATE_LIMIT", env_value(nexus, "DISPATCH_RATE_LIMIT"), min_dispatch)
require_int("RATE_LIMIT_PER_MINUTE", env_value(nexus, "RATE_LIMIT_PER_MINUTE"), min_ip)
require_int("MAX_CONCURRENT_TASKS", env_value(workers, "MAX_CONCURRENT_TASKS"), min_worker)
PY

if [[ "$REQUIRE_LIVE" != "true" ]]; then
  echo ""
  echo "Rendered preflight passed. For Run 4b, converge staging first:"
  echo "  kubectl apply -k ${OVERLAY}"
  echo "  ./scripts/verify-staging-load-run4b-preflight.sh --require-live"
  exit 0
fi

echo ""
echo "== Run 4b live preflight (namespace=${NS}) =="

nexus_replicas="$(kubectl -n "$NS" get deploy nexus-api -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
nexus_ready="$(kubectl -n "$NS" get deploy nexus-api -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)"
require_int_eq "live nexus-api replicas" "${nexus_replicas:-0}" "$EXPECTED_NEXUS_REPLICAS"
require_int_eq "live nexus-api readyReplicas" "${nexus_ready:-0}" "$EXPECTED_NEXUS_REPLICAS"

hpa_min="$(kubectl -n "$NS" get hpa nexus-api-hpa -o jsonpath='{.spec.minReplicas}' 2>/dev/null || true)"
hpa_max="$(kubectl -n "$NS" get hpa nexus-api-hpa -o jsonpath='{.spec.maxReplicas}' 2>/dev/null || true)"
require_int_eq "live nexus-api-hpa minReplicas" "${hpa_min:-0}" "$EXPECTED_NEXUS_REPLICAS"
require_int_eq "live nexus-api-hpa maxReplicas" "${hpa_max:-0}" "$EXPECTED_NEXUS_REPLICAS"

dispatch_limit="$(kubectl -n "$NS" get deploy nexus-api \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DISPATCH_RATE_LIMIT")].value}' 2>/dev/null || true)"
ip_limit="$(kubectl -n "$NS" get deploy nexus-api \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="RATE_LIMIT_PER_MINUTE")].value}' 2>/dev/null || true)"
worker_concurrency="$(kubectl -n "$NS" get deploy workers \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MAX_CONCURRENT_TASKS")].value}' 2>/dev/null || true)"

require_int_ge "live DISPATCH_RATE_LIMIT" "${dispatch_limit:-0}" "$MIN_DISPATCH_RATE"
require_int_ge "live RATE_LIMIT_PER_MINUTE" "${ip_limit:-0}" "$MIN_IP_RATE"
require_int_ge "live MAX_CONCURRENT_TASKS" "${worker_concurrency:-0}" "$MIN_WORKER_CONCURRENCY"

pass "Run 4b live preflight passed"
