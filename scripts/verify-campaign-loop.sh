#!/usr/bin/env bash
# API-level Phase 2 campaign loop verification (operator backlog 5b).
#
# Exercises: import → schedule-social → HITL approve → CRM handoff → Tulana feedback.
# Requires a Janua Bearer token with tenant org scope (not guest), or on
# --staging falls back to WORKER_API_TOKEN from selva-staging-secrets
# (with X-Selva-Tenant-Org) when no JWT is set.
#
# Usage:
#   AUTH_TOKEN=<jwt> ./scripts/verify-campaign-loop.sh
#   AUTH_TOKEN=<jwt> ./scripts/verify-campaign-loop.sh --staging
#   ./scripts/verify-campaign-loop.sh --staging   # uses worker token via kubectl
#
# Env (first match wins): AUTH_TOKEN, STAGING_CAMPAIGN_TEST_TOKEN, STAGING_LOAD_TEST_TOKEN
# Staging worker fallback: STAGING_TENANT_ORG (default madfam), WORKER_API_TOKEN
#
# Exit 0 when all applicable checks pass or when no token is set (SKIP).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${BASE_URL:-http://localhost:4300}"
MODE="${1:-local}"
FIXTURE="${ROOT}/scripts/fixtures/staging-smoke-pack.json"
FAILURES=()

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; FAILURES+=("$*"); }
skip() { echo "SKIP: $*"; }

echo "== Campaign loop verification (mode=$MODE) =="

if [[ "$MODE" == "--staging" ]]; then
  BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
fi

TOKEN="${AUTH_TOKEN:-${STAGING_CAMPAIGN_TEST_TOKEN:-${STAGING_LOAD_TEST_TOKEN:-}}}"
TENANT_ORG_HEADER=()
if [[ -z "$TOKEN" && "$MODE" == "--staging" ]]; then
  if [[ -z "${WORKER_API_TOKEN:-}" ]] && command -v kubectl >/dev/null 2>&1; then
    WORKER_API_TOKEN="$(kubectl -n selva-staging get secret selva-staging-secrets \
      -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
  fi
  if [[ -n "${WORKER_API_TOKEN:-}" ]]; then
    TOKEN="$WORKER_API_TOKEN"
    TENANT_ORG_HEADER=(-H "X-Selva-Tenant-Org: ${STAGING_TENANT_ORG:-madfam}")
    pass "using WORKER_API_TOKEN for staging API loop (org=${STAGING_TENANT_ORG:-madfam})"
  fi
fi
if [[ -z "$TOKEN" ]]; then
  skip "no AUTH_TOKEN / STAGING_CAMPAIGN_TEST_TOKEN — API loop not run"
  skip "set STAGING_CAMPAIGN_TEST_TOKEN in GitHub secrets for CI soak"
  exit 0
fi

if [[ ! -f "$FIXTURE" ]]; then
  fail "fixture missing: $FIXTURE"
  exit 1
fi

RUN_ID="$(date +%s)-$$"
AUTH_HEADER="Authorization: Bearer ${TOKEN}"

api_post() {
  local path="$1"
  local body="$2"
  local idem_key="${3:-}"
  local extra=()
  if [[ -n "$idem_key" ]]; then
    extra+=(-H "Idempotency-Key: ${idem_key}")
  fi
  local headers=(-H "Content-Type: application/json" -H "$AUTH_HEADER")
  if ((${#TENANT_ORG_HEADER[@]} > 0)); then
    headers+=("${TENANT_ORG_HEADER[@]}")
  fi
  curl -sS -w "\n%{http_code}" \
    -X POST "${BASE_URL}${path}" \
    "${headers[@]}" \
    "${extra[@]}" \
    --data "$body"
}

api_patch() {
  local path="$1"
  local body="$2"
  local headers=(-H "Content-Type: application/json" -H "$AUTH_HEADER")
  if ((${#TENANT_ORG_HEADER[@]} > 0)); then
    headers+=("${TENANT_ORG_HEADER[@]}")
  fi
  curl -sS -w "\n%{http_code}" \
    -X PATCH "${BASE_URL}${path}" \
    "${headers[@]}" \
    --data "$body"
}

parse_response() {
  local raw="$1"
  BODY="$(printf '%s' "$raw" | sed '$d')"
  CODE="$(printf '%s' "$raw" | tail -n1)"
}

echo "--- import Tulana pack ---"
IMPORT_BODY="$(cat "$FIXTURE")"
IMPORT_RAW="$(api_post "/api/v1/campaigns/import-tulana-pack" "$IMPORT_BODY" "campaign-loop-import-${RUN_ID}")"
parse_response "$IMPORT_RAW"
if [[ "$CODE" == "200" ]]; then
  pass "import-tulana-pack (200)"
elif [[ "$CODE" == "401" || "$CODE" == "403" ]]; then
  fail "import-tulana-pack auth failed (${CODE}) — check Janua staging token"
else
  fail "import-tulana-pack expected 200, got ${CODE}: ${BODY}"
fi

echo "--- schedule social (HITL) ---"
SCHEDULE_BODY="$(python3 - <<'PY'
import json
from datetime import UTC, datetime, timedelta

when = (datetime.now(UTC) + timedelta(minutes=45)).isoformat()
print(json.dumps({
    "sku_key": "avala__issuer",
    "platform": "reddit",
    "require_hitl": True,
    "posts": [{
        "scheduled_for": when,
        "payload": {
            "subreddit": "test",
            "title": "Staging campaign loop verify",
            "body": "Proof-backed copy only — automated soak",
        },
    }],
}))
PY
)"
SCHEDULE_RAW="$(api_post "/api/v1/campaigns/schedule-social" "$SCHEDULE_BODY" "campaign-loop-schedule-${RUN_ID}")"
parse_response "$SCHEDULE_RAW"
ACTION_ID=""
if [[ "$CODE" == "201" ]]; then
  pass "schedule-social (201)"
  ACTION_ID="$(printf '%s' "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['created'][0]['id'])")"
else
  fail "schedule-social expected 201, got ${CODE}: ${BODY}"
fi

if [[ -n "$ACTION_ID" ]]; then
  echo "--- HITL approve scheduled post ---"
  HITL_RAW="$(api_patch "/api/v1/scheduled-actions/${ACTION_ID}/hitl" '{"decision":"approved"}')"
  parse_response "$HITL_RAW"
  if [[ "$CODE" == "200" ]] && printf '%s' "$BODY" | grep -q '"hitl_status":"approved"'; then
    pass "scheduled-actions HITL approve (200)"
  else
    fail "HITL approve expected 200 approved, got ${CODE}: ${BODY}"
  fi
fi

echo "--- CRM handoff ---"
HANDOFF_BODY="$(python3 - <<'PY'
import json
from pathlib import Path

fixture = json.loads(Path("scripts/fixtures/staging-smoke-pack.json").read_text())
pack = fixture["packs"][0]
print(json.dumps({
    "sku_key": pack["sku_key"],
    "audience": pack["audience"],
    "draft_variants": ["Staging loop subject A"],
    "tulana_pack": pack,
}))
PY
)"
HANDOFF_RAW="$(api_post "/api/v1/campaigns/crm-handoff" "$HANDOFF_BODY" "campaign-loop-handoff-${RUN_ID}")"
parse_response "$HANDOFF_RAW"
HANDOFF_ID=""
if [[ "$CODE" == "201" ]]; then
  pass "crm-handoff (201)"
  HANDOFF_ID="$(printf '%s' "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('handoff_id',''))")"
else
  fail "crm-handoff expected 201, got ${CODE}: ${BODY}"
fi

echo "--- Tulana feedback ---"
FEEDBACK_BODY="$(python3 - <<PY
import json
print(json.dumps({
    "sku_key": "avala__issuer",
    "summary": "Staging campaign loop verify — automated soak",
    "outcomes": [{"metric": "verify_run", "value": 1, "source": "verify-campaign-loop"}],
    "handoff_id": "${HANDOFF_ID}",
}))
PY
)"
FEEDBACK_RAW="$(api_post "/api/v1/campaigns/tulana-feedback" "$FEEDBACK_BODY" "campaign-loop-feedback-${RUN_ID}")"
parse_response "$FEEDBACK_RAW"
if [[ "$CODE" == "200" ]]; then
  pass "tulana-feedback (200)"
elif [[ "$CODE" == "503" || "$CODE" == "502" ]]; then
  skip "tulana-feedback not configured or upstream missing (${CODE}) — wire TULANA_API_URL + secret + buyer-signal route"
else
  fail "tulana-feedback expected 200 or 503/502 skip, got ${CODE}: ${BODY}"
fi

if ((${#FAILURES[@]} > 0)); then
  echo ""
  echo "Campaign loop verification failed:"
  printf ' - %s\n' "${FAILURES[@]}"
  exit 1
fi

echo ""
echo "Campaign loop verification passed."
