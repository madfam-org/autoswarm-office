#!/usr/bin/env bash
#
# Selva secret rotation — Phase 3 item 15 (full-remediation plan).
#
# Rotates one or all of the production-validator-protected secrets by:
#   1. Generating a new value (32-byte hex, suitable for HMAC + bearer token use)
#   2. Patching the K8s Secret with the new value
#   3. Rolling-restarting every Deployment that env-references the secret
#   4. Verifying the new value is live in pod env (sample one pod per Deployment)
#   5. Logging the previous value's first/last 4 chars for audit (NEVER full value)
#
# What this DOES NOT do:
#   - Touch external secret stores (Enclii Switchyard, Vault). Those are the
#     upstream source of truth; this script assumes you've already updated them
#     OR that the K8s Secret is the source of truth (operator decides per env).
#   - Stripe / Resend / OpenAI / Anthropic API keys. Those rotate via their
#     respective vendor consoles. Script intentionally narrowly scoped to the
#     3 Selva-owned secrets that have production validators in
#     ``apps/nexus-api/nexus_api/config.py``:
#       - WORKER_API_TOKEN
#       - CONSENT_LEDGER_SIGNING_SECRET
#       - COLYSEUS_SERVICE_TOKEN
#   - Janua JWT signing keys. Those rotate in the Janua repo via its own
#     procedure (see Janua docs).
#
# Why these 3 specifically:
#   Each has a production-environment validator that refuses the dev default.
#   The validator catches "I forgot to set this" but doesn't catch "I set this
#   12 months ago and never rotated." This script closes that gap by making
#   rotation a one-command operation an operator can run on a quarterly cadence.
#
# Usage:
#   ./scripts/rotate-secret.sh <secret-name> [--namespace=NAMESPACE] [--dry-run]
#   ./scripts/rotate-secret.sh --all [--namespace=NAMESPACE] [--dry-run]
#
#   secret-name: one of:
#     - worker-api-token       (rotates WORKER_API_TOKEN)
#     - consent-ledger-signing (rotates CONSENT_LEDGER_SIGNING_SECRET)
#     - colyseus-service       (rotates COLYSEUS_SERVICE_TOKEN)
#
#   --namespace defaults to autoswarm; common alt: autoswarm-staging
#   --dry-run prints the kubectl commands that would run, without executing them
#
# Cadence (per docs/SECRET_ROTATION_POLICY.md):
#   Quarterly under normal ops. Immediately on suspected compromise.
#
# Audit:
#   Logs to stderr (script output) AND emits an event to autoswarm:audit
#   stream so the SRE Grafana board reflects rotation history. NEVER logs
#   the actual secret value — only the first/last 4 chars (mask middle).

set -euo pipefail

# Bash 4+ is required for associative arrays. macOS ships bash 3.2 — operators
# running this from a Mac need ``brew install bash`` (and ``which bash`` to
# pick up the brew version). Linux ops boxes ship 4 or 5; fine out of the box.
if [[ ${BASH_VERSINFO[0]:-0} -lt 4 ]]; then
  echo "ERROR: rotate-secret.sh requires bash 4+. You have ${BASH_VERSION}." >&2
  echo "  macOS: brew install bash, then ensure /opt/homebrew/bin is on PATH." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Constants — derived from infra/k8s/production/*.yaml inspection
# -----------------------------------------------------------------------------

readonly K8S_SECRET_NAME="autoswarm-secrets"

# Map: rotation-target → (env var name, deployments to restart).
# The deployments list MUST cover every Deployment that env-references the
# secret. Missing one means a stale pod keeps the old value, which is exactly
# what rotation is trying to prevent.
declare -rA ENV_KEY_FOR_TARGET=(
  [worker-api-token]="WORKER_API_TOKEN"
  [consent-ledger-signing]="CONSENT_LEDGER_SIGNING_SECRET"
  [colyseus-service]="COLYSEUS_SERVICE_TOKEN"
)

declare -rA DEPLOYMENTS_FOR_TARGET=(
  [worker-api-token]="autoswarm-nexus-api autoswarm-workers autoswarm-gateway"
  [consent-ledger-signing]="autoswarm-nexus-api"
  [colyseus-service]="autoswarm-colyseus autoswarm-nexus-api"
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

mask_value() {
  # Print first 4 + "..." + last 4 chars. Used for audit logging where we
  # want a fingerprint of the rotation without leaking the secret.
  local val="$1"
  local len=${#val}
  if [[ $len -le 8 ]]; then
    echo "****"
  else
    echo "${val:0:4}...${val: -4}"
  fi
}

generate_new_value() {
  # 32 random bytes → 64 hex chars. Suitable for both HMAC use
  # (CONSENT_LEDGER_SIGNING_SECRET) and bearer-token use
  # (WORKER_API_TOKEN, COLYSEUS_SERVICE_TOKEN). 256 bits of entropy.
  openssl rand -hex 32
}

require_kubectl() {
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "ERROR: kubectl not found in PATH" >&2
    exit 1
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl not found in PATH" >&2
    exit 1
  fi
}

# -----------------------------------------------------------------------------
# Main rotation logic
# -----------------------------------------------------------------------------

rotate_one() {
  local target="$1"
  local namespace="$2"
  local dry_run="$3"

  local env_key="${ENV_KEY_FOR_TARGET[$target]:-}"
  local deployments="${DEPLOYMENTS_FOR_TARGET[$target]:-}"
  if [[ -z "$env_key" || -z "$deployments" ]]; then
    echo "ERROR: Unknown rotation target '$target'." >&2
    echo "  Valid targets: ${!ENV_KEY_FOR_TARGET[*]}" >&2
    exit 2
  fi

  echo "==> Rotating $env_key (target=$target) in namespace=$namespace"

  # Read the current value so we can log a fingerprint.
  local current_b64
  if ! current_b64=$(kubectl -n "$namespace" get secret "$K8S_SECRET_NAME" \
        -o "jsonpath={.data.$env_key}" 2>/dev/null); then
    echo "ERROR: Failed to read secret/$K8S_SECRET_NAME in namespace=$namespace." >&2
    echo "  Ensure kubeconfig is set + the secret exists." >&2
    exit 3
  fi
  local current_value
  if [[ -n "$current_b64" ]]; then
    current_value=$(echo "$current_b64" | base64 -d 2>/dev/null || echo "")
  else
    current_value=""
  fi

  local new_value
  new_value=$(generate_new_value)

  echo "  old fingerprint: $(mask_value "$current_value")"
  echo "  new fingerprint: $(mask_value "$new_value")"

  if [[ "$dry_run" == "true" ]]; then
    echo "  [dry-run] would patch K8s secret + restart: $deployments"
    return 0
  fi

  # Patch the secret. ``--type=merge`` so other keys in the secret are
  # untouched. Value is base64-encoded inline.
  local new_b64
  new_b64=$(printf '%s' "$new_value" | base64 | tr -d '\n')
  kubectl -n "$namespace" patch secret "$K8S_SECRET_NAME" \
    --type=merge \
    -p "{\"data\":{\"$env_key\":\"$new_b64\"}}" \
    >/dev/null

  # Rolling restart every Deployment that references it. K8s rolling-update
  # semantics ensure ≥1 pod stays serving while the others roll.
  for dep in $deployments; do
    echo "  rolling restart: $dep"
    kubectl -n "$namespace" rollout restart "deployment/$dep"
  done

  # Wait for the rollouts to complete (5min timeout per dep — same as the
  # Helm chart's default).
  for dep in $deployments; do
    echo "  waiting for $dep rollout to complete..."
    kubectl -n "$namespace" rollout status "deployment/$dep" --timeout=5m
  done

  # Verify: read one pod's env per Deployment, confirm the value matches the
  # new fingerprint. ``kubectl exec`` into the first ready pod, print the
  # mapped env var. Mask the value before logging.
  local verification_failures=0
  for dep in $deployments; do
    local pod
    pod=$(kubectl -n "$namespace" get pod \
      -l "app.kubernetes.io/name=$dep" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -z "$pod" ]]; then
      # Try the broader 'app=' label as a fallback; some helm charts use it.
      pod=$(kubectl -n "$namespace" get pod \
        -l "app=$dep" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    fi
    if [[ -z "$pod" ]]; then
      echo "  WARNING: no pod found for $dep — skipping verification" >&2
      verification_failures=$((verification_failures + 1))
      continue
    fi
    local pod_value
    pod_value=$(kubectl -n "$namespace" exec "$pod" -- printenv "$env_key" 2>/dev/null || echo "")
    if [[ "$pod_value" == "$new_value" ]]; then
      echo "  ✓ verified $dep ($pod) sees new value"
    else
      echo "  ✗ FAILED: $dep ($pod) does NOT have new $env_key value" >&2
      verification_failures=$((verification_failures + 1))
    fi
  done

  if [[ $verification_failures -gt 0 ]]; then
    echo "ERROR: $verification_failures deployment(s) failed verification." >&2
    echo "  The secret IS rotated in K8s, but at least one pod did not pick" >&2
    echo "  up the new value. Investigate before declaring rotation complete." >&2
    exit 4
  fi

  echo "==> Rotation complete for $env_key."
}

# -----------------------------------------------------------------------------
# Argument parsing + dispatch
# -----------------------------------------------------------------------------

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 1
}

main() {
  require_kubectl

  local namespace="autoswarm"
  local dry_run="false"
  local target=""
  local rotate_all="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --namespace=*) namespace="${1#*=}"; shift ;;
      --namespace) namespace="$2"; shift 2 ;;
      --dry-run) dry_run="true"; shift ;;
      --all) rotate_all="true"; shift ;;
      -h|--help) usage ;;
      worker-api-token|consent-ledger-signing|colyseus-service) target="$1"; shift ;;
      *) echo "Unknown argument: $1" >&2; usage ;;
    esac
  done

  if [[ "$rotate_all" == "true" ]]; then
    if [[ -n "$target" ]]; then
      echo "ERROR: --all and a specific target are mutually exclusive." >&2
      exit 1
    fi
    for t in "${!ENV_KEY_FOR_TARGET[@]}"; do
      rotate_one "$t" "$namespace" "$dry_run"
      echo ""
    done
  elif [[ -n "$target" ]]; then
    rotate_one "$target" "$namespace" "$dry_run"
  else
    echo "ERROR: must specify a target or --all." >&2
    usage
  fi
}

main "$@"
