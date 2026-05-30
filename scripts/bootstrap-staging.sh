#!/usr/bin/env bash
# PP.4 — operator bootstrap for autoswarm-office staging tier.
#
# Runs in ROI order:
#   1. Cloudflare DNS + tunnel ingress (requires CF API token)
#   2. DNS propagation check
#   3. Print / optional run cluster steps (ArgoCD app + secrets)
#   4. Enable GitHub STAGING_* variables + STAGING_ENABLED when ready
#
# Prerequisites:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
#   kubectl context pointed at the prod cluster (for steps 3+)
#
# Usage:
#   ./scripts/bootstrap-staging.sh --dry-run
#   ./scripts/bootstrap-staging.sh --cloudflare-only
#   ./scripts/bootstrap-staging.sh --enable-github-vars   # after smoke passes

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=false
CF_ONLY=false
ENABLE_GH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --cloudflare-only) CF_ONLY=true ;;
    --enable-github-vars) ENABLE_GH=true ;;
    -h|--help)
      sed -n '1,22p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

cf_args=()
if $DRY_RUN; then cf_args+=(--dry-run); fi

echo "== Step 1: Cloudflare DNS + tunnel ingress =="
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  if [[ -f "${HOME}/.enclii/credentials" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/../enclii/scripts/lib/cloudflare-credentials.sh" 2>/dev/null \
      || source "/Users/aldoruizluna/labspace/enclii/scripts/lib/cloudflare-credentials.sh"
    load_cloudflare_credentials || true
  fi
fi
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  echo "WARN CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID not set — skipping apply."
  echo "     Configure ~/.enclii/credentials or export env vars, then re-run."
else
  python3 "$ROOT/scripts/apply-cloudflare-infra.py" "${cf_args[@]}" --merge
fi

echo ""
echo "== Step 2: DNS propagation check =="
STAGING_HOSTS=(
  staging-api.selva.town
  staging.selva.town
  staging-admin.selva.town
  staging-ws.selva.town
  staging-gw.selva.town
)
dns_ok=true
for host in "${STAGING_HOSTS[@]}"; do
  if dig +short "$host" | grep -q .; then
    echo "OK   $host resolves"
  else
    echo "WARN $host still NXDOMAIN (DNS may need a few minutes)"
    dns_ok=false
  fi
done

if $CF_ONLY; then
  exit 0
fi

echo ""
echo "== Step 3: Cluster bootstrap (operator) =="
cat <<'EOF'
When DNS resolves, on the prod cluster:

  # Register staging ArgoCD app (creates autoswarm-staging namespace)
  kubectl apply -f infra/argocd/staging.yaml
  argocd app sync autoswarm-office-staging

  # If sync fails on backup prune or nexus-api CreateContainerConfigError:
  ./scripts/reconcile-staging-argocd.sh --ensure-dhanam-secret

  # Provision secrets (see infra/k8s/overlays/staging/staging-secrets-template.yaml)
  kubectl create namespace autoswarm-staging --dry-run=client -o yaml | kubectl apply -f -
  # ... create autoswarm-staging-{secrets,llm-secrets,admin-auth}

  # Trigger staging image build (after STAGING_ENABLED=true):
  gh workflow run staging-deploy.yml --ref main
EOF

if $ENABLE_GH; then
  echo ""
  echo "== Step 4: GitHub repo variables =="
  if ! $dns_ok; then
    echo "error: staging DNS not propagated — not enabling STAGING_ENABLED" >&2
    exit 1
  fi
  gh variable set STAGING_API_URL --body "https://staging-api.selva.town"
  gh variable set STAGING_UI_URL --body "https://staging.selva.town"
  gh variable set STAGING_ADMIN_URL --body "https://staging-admin.selva.town"
  gh variable set STAGING_WS_URL --body "https://staging-ws.selva.town"
  gh variable set STAGING_GW_URL --body "https://staging-gw.selva.town"
  gh variable set STAGING_ENABLED --body "true"
  echo "OK   STAGING_* variables set; push to main or dispatch staging-deploy.yml"
fi

echo ""
echo "Post-bootstrap verification:"
echo "  ./scripts/staging-smoke.sh"
echo "  k6 run -e BASE_URL=https://staging-api.selva.town tests/load/concurrent-100-swarmtasks.js"
