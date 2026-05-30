#!/usr/bin/env bash
# Clone prod autoswarm secrets into autoswarm-staging with isolated DB name.
#
# Requires kubectl access to the prod cluster. Idempotent — skips existing secrets
# unless --force is passed.
#
# Usage:
#   ./scripts/bootstrap-staging-secrets.sh
#   ./scripts/bootstrap-staging-secrets.sh --force

set -euo pipefail

FORCE=false
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
  esac
done

PROD_NS=autoswarm
STAGING_NS=autoswarm-staging

kubectl create namespace "$STAGING_NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace "$STAGING_NS" \
  enclii.dev/type=application \
  enclii.dev/data-access=true \
  app.kubernetes.io/part-of=autoswarm-office \
  autoswarm.dev/environment=staging \
  --overwrite >/dev/null

clone_secret() {
  local src=$1
  local dst=$2
  local rewrite_db=${3:-0}
  if kubectl get secret "$dst" -n "$STAGING_NS" >/dev/null 2>&1 && [[ "$FORCE" != true ]]; then
    echo "OK   $dst already exists (use --force to recreate)"
    return 0
  fi
  export REWRITE_DB="$rewrite_db"
  export DST="$dst"
  export STAGING_NS="$STAGING_NS"
  kubectl get secret "$src" -n "$PROD_NS" -o json \
    | python3 -c "
import json, sys, base64, os
doc = json.load(sys.stdin)
doc['metadata'] = {
    'name': os.environ['DST'],
    'namespace': os.environ['STAGING_NS'],
}
for k in ('resourceVersion', 'uid', 'creationTimestamp', 'managedFields'):
    doc.pop(k, None)
data = doc.get('data') or {}
if os.environ.get('REWRITE_DB') == '1':
    db = data.get('database-url')
    if db:
        raw = base64.b64decode(db).decode()
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(raw)
        if parsed.path in ('/autoswarm', '/autoswarm/'):
            parsed = parsed._replace(path='/autoswarm_staging')
            raw = urlunparse(parsed)
        data['database-url'] = base64.b64encode(raw.encode()).decode()
doc['data'] = data
print(json.dumps(doc))
" \
    | kubectl apply -f -
  echo "OK   cloned $src -> $dst"
}

if ! kubectl get secret autoswarm-secrets -n "$PROD_NS" >/dev/null 2>&1; then
  echo "error: prod secret autoswarm-secrets not found in $PROD_NS" >&2
  exit 1
fi

clone_secret autoswarm-secrets autoswarm-staging-secrets 1

if kubectl get secret autoswarm-llm-secrets -n "$PROD_NS" >/dev/null 2>&1; then
  clone_secret autoswarm-llm-secrets autoswarm-staging-llm-secrets 0
else
  echo "WARN autoswarm-llm-secrets missing in prod — create manually"
fi

if kubectl get secret autoswarm-admin-auth -n "$PROD_NS" >/dev/null 2>&1; then
  clone_secret autoswarm-admin-auth autoswarm-staging-admin-auth 0
else
  echo "WARN autoswarm-admin-auth missing in prod — Janua staging client still required"
fi

echo ""
echo "Secrets ready in $STAGING_NS. Ensure Postgres database autoswarm_staging exists."

if kubectl get secret ghcr-credentials -n "$PROD_NS" >/dev/null 2>&1; then
  clone_secret ghcr-credentials ghcr-credentials 0
fi
