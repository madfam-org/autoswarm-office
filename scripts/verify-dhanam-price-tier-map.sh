#!/usr/bin/env bash
# Verify Dhanam Stripe price -> Selva tier mapping and webhook fan-out coverage.
#
# Selva expects Dhanam-normalized billing webhooks to include a Selva tier slug.
# This script checks Dhanam secret/config coverage without printing secret values.
#
# Usage:
#   ./scripts/verify-dhanam-price-tier-map.sh --staging
#   ./scripts/verify-dhanam-price-tier-map.sh --staging --require-all
#   ./scripts/verify-dhanam-price-tier-map.sh --require-map --require-webhook
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE=prod
DHANAM_NS="${DHANAM_NS:-enclii-dhanam}"
SECRET_NAME="${DHANAM_SECRET_NAME:-dhanam-secrets}"
REQUIRE_MAP=false
REQUIRE_WEBHOOK=false
EXPECTED_WEBHOOK_URL="${SELVA_DHANAM_WEBHOOK_URL:-}"

usage() {
  awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"
}

for arg in "$@"; do
  case "$arg" in
    --staging)
      MODE=staging
      DHANAM_NS="${DHANAM_STAGING_NS:-enclii-dhanam-staging}"
      ;;
    --prod)
      MODE=prod
      DHANAM_NS="${DHANAM_NS:-enclii-dhanam}"
      ;;
    --require-map)
      REQUIRE_MAP=true
      ;;
    --require-webhook)
      REQUIRE_WEBHOOK=true
      ;;
    --require-all)
      REQUIRE_MAP=true
      REQUIRE_WEBHOOK=true
      ;;
    --namespace=*)
      DHANAM_NS="${arg#*=}"
      ;;
    --secret=*)
      SECRET_NAME="${arg#*=}"
      ;;
    --webhook-url=*)
      EXPECTED_WEBHOOK_URL="${arg#*=}"
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

if [[ -z "$EXPECTED_WEBHOOK_URL" ]]; then
  if [[ "$MODE" == "staging" ]]; then
    EXPECTED_WEBHOOK_URL="https://staging-api.selva.town/api/v1/billing/webhooks/dhanam"
  else
    EXPECTED_WEBHOOK_URL="https://api.selva.town/api/v1/billing/webhooks/dhanam"
  fi
fi

pass() { echo "OK: $*"; }
skip() { echo "SKIP: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

echo "== Dhanam price->tier verification (mode=${MODE}, ns=${DHANAM_NS}, secret=${SECRET_NAME}) =="

if ! command -v kubectl >/dev/null 2>&1; then
  if $REQUIRE_MAP || $REQUIRE_WEBHOOK; then
    fail "kubectl unavailable; cannot satisfy required Dhanam verification"
  fi
  skip "kubectl unavailable"
  exit 0
fi

SECRET_JSON="$(kubectl -n "$DHANAM_NS" get secret "$SECRET_NAME" -o json 2>/dev/null || true)"
if [[ -z "$SECRET_JSON" ]]; then
  fail "secret ${SECRET_NAME} not readable in ${DHANAM_NS}"
fi

SECRET_FILE="$(mktemp -t selva-dhanam-secret.XXXXXX)"
trap 'rm -f "$SECRET_FILE"' EXIT
printf '%s' "$SECRET_JSON" > "$SECRET_FILE"

export EXPECTED_WEBHOOK_URL REQUIRE_MAP REQUIRE_WEBHOOK
python3 - "$SECRET_FILE" <<'PY'
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

pricing_path = Path("infra/pricing/selva-tiers.json")
pricing = json.loads(pricing_path.read_text())
tiers_cfg = pricing["dhanam_subscription_daily_limits"]["tiers"]
required_tiers = list(tiers_cfg.keys())
required_tier_set = set(required_tiers)

secret = json.loads(Path(sys.argv[1]).read_text())
encoded = secret.get("data", {}) or {}

def decode_key(key: str) -> str:
    raw = encoded.get(key)
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""

def normalize_tier(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")

def note(prefix: str, message: str) -> None:
    print(f"{prefix}: {message}")

covered: dict[str, set[str]] = {tier: set() for tier in required_tiers}

# Per-tier env keys are the most explicit contract, sourced from the pricing SOT.
for tier, cfg in tiers_cfg.items():
    env_key = cfg.get("stripe_price_id_env_key")
    if env_key and decode_key(env_key):
        covered[tier].add(env_key)

def cover_from_mapping(name: str, value: Any) -> None:
    """Accept both price->tier and tier->price mapping shapes."""
    if isinstance(value, dict):
        for key, val in value.items():
            key_tier = normalize_tier(key)
            val_tier = normalize_tier(val)
            if key_tier in required_tier_set and str(val or "").strip():
                covered[key_tier].add(name)
            if val_tier in required_tier_set and str(key or "").strip():
                covered[val_tier].add(name)
            if isinstance(val, dict):
                nested_tier = normalize_tier(
                    val.get("tier")
                    or val.get("tier_slug")
                    or val.get("tierSlug")
                    or val.get("subscription_tier")
                )
                price_id = val.get("price_id") or val.get("stripe_price_id") or key
                if nested_tier in required_tier_set and str(price_id or "").strip():
                    covered[nested_tier].add(name)
    elif isinstance(value, list):
        for item in value:
            cover_from_mapping(name, item)

def parse_loose_mapping(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in re.split(r"[\n,;]+", raw):
        item = part.strip()
        if not item:
            continue
        if "=" in item:
            key, val = item.split("=", 1)
        elif ":" in item:
            key, val = item.split(":", 1)
        else:
            continue
        pairs[key.strip()] = val.strip()
    return pairs

for map_key in ("PRICE_TIER_MAP", "STRIPE_PRICE_TO_TIER_MAP"):
    raw = decode_key(map_key)
    if not raw:
        continue
    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = parse_loose_mapping(raw)
    cover_from_mapping(map_key, parsed)

map_ok = True
for tier in required_tiers:
    sources = sorted(covered[tier])
    if sources:
        note("OK", f"tier {tier} has Dhanam price mapping coverage via {', '.join(sources)}")
    else:
        note("MISS", f"tier {tier} has no Dhanam price mapping coverage")
        map_ok = False

product_webhook_urls = decode_key("PRODUCT_WEBHOOK_URLS")
expected_webhook_url = os.environ["EXPECTED_WEBHOOK_URL"]
webhook_ok = bool(product_webhook_urls and expected_webhook_url in product_webhook_urls)
if webhook_ok:
    note("OK", "PRODUCT_WEBHOOK_URLS includes expected Selva billing webhook URL")
else:
    note("MISS", "PRODUCT_WEBHOOK_URLS does not include expected Selva billing webhook URL")

if decode_key("DHANAM_WEBHOOK_SECRET"):
    note("OK", "DHANAM_WEBHOOK_SECRET present in Dhanam secret")
else:
    note("MISS", "DHANAM_WEBHOOK_SECRET missing from Dhanam secret")

require_map = os.environ.get("REQUIRE_MAP") == "true"
require_webhook = os.environ.get("REQUIRE_WEBHOOK") == "true"

failed = False
if require_map and not map_ok:
    note("FAIL", "required price->tier map coverage is incomplete")
    failed = True
elif not map_ok:
    note("SKIP", "price->tier map incomplete; rerun with --require-map after Dhanam catalog is configured")

if require_webhook and not webhook_ok:
    note("FAIL", "required PRODUCT_WEBHOOK_URLS coverage is incomplete")
    failed = True
elif not webhook_ok:
    note("SKIP", "webhook fan-out incomplete; rerun with --require-webhook after Dhanam secret is configured")

sys.exit(1 if failed else 0)
PY

pass "Dhanam price->tier verification completed"
if [[ "$MODE" == "staging" ]]; then
  echo "Next: run ./scripts/verify-dhanam-billing-path.sh --staging"
else
  echo "Next: run BASE_URL=https://api.selva.town ./scripts/verify-dhanam-billing-path.sh"
fi
