#!/usr/bin/env bash
# Reconcile selva-office-staging when ArgoCD sync fails on backup prune
# or nexus-api rolls with CreateContainerConfigError (missing DHANAM_WEBHOOK_SECRET).
#
# Enclii-first: prefers `enclii ops apps sync`. kubectl deletes below are
# break-glass for resources the staging overlay excludes via $patch: delete.
#
# Usage:
#   ./scripts/reconcile-staging-argocd.sh --dry-run
#   ./scripts/reconcile-staging-argocd.sh
#   ./scripts/reconcile-staging-argocd.sh --ensure-dhanam-secret
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY_RUN=false
ENSURE_DHANAM=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --ensure-dhanam-secret) ENSURE_DHANAM=true ;;
    -h|--help)
      sed -n '1,18p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

run() {
  if $DRY_RUN; then
    echo "DRY: $*"
  else
    "$@"
  fi
}

echo "== Step 1: Remove staging backup stack excluded from overlay =="
for obj in \
  "cronjob/postgres-backup" \
  "externalsecret/postgres-backup-credentials" \
  "pvc/postgres-backup-pvc"; do
  run kubectl -n selva-staging delete "$obj" --ignore-not-found
done
run kubectl delete storageclass longhorn-selva-backup --ignore-not-found

if $ENSURE_DHANAM; then
  echo ""
  echo "== Step 2: Ensure DHANAM_WEBHOOK_SECRET in selva-staging-secrets =="
  if kubectl -n selva-staging get secret selva-staging-secrets \
    -o jsonpath='{.data.DHANAM_WEBHOOK_SECRET}' 2>/dev/null | grep -q .; then
    echo "OK   DHANAM_WEBHOOK_SECRET already present"
  else
    secret_val="$(openssl rand -hex 32)"
    run kubectl -n selva-staging patch secret selva-staging-secrets \
      --type merge \
      -p "{\"stringData\":{\"DHANAM_WEBHOOK_SECRET\":\"${secret_val}\"}}"
    echo "OK   DHANAM_WEBHOOK_SECRET generated and patched (configure same value in Dhanam when live)"
  fi
fi

echo ""
echo "== Step 3: ArgoCD sync via Enclii =="
if command -v enclii >/dev/null 2>&1; then
  if $DRY_RUN; then
    echo "DRY: enclii ops apps sync selva-office-staging --apply --reason reconcile-staging-argocd"
  else
    enclii ops apps sync selva-office-staging \
      --apply \
      --reason "reconcile-staging-argocd.sh: prune backup stack + roll deployments"
  fi
else
  echo "WARN enclii not installed — run: argocd app sync selva-office-staging"
fi

echo ""
echo "== Step 4: Verify campaign routes =="
if $DRY_RUN; then
  echo "DRY: ./scripts/verify-campaign-path.sh --staging"
else
  for attempt in $(seq 1 12); do
    if ./scripts/verify-campaign-path.sh --staging; then
      exit 0
    fi
    echo "attempt ${attempt}/12: routes not ready, sleeping 15s"
    sleep 15
  done
  echo "FAIL: campaign routes still missing after reconcile" >&2
  exit 1
fi
