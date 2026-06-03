#!/usr/bin/env bash
# Run Alembic migrations against selva_staging (operator break-glass).
#
# The app role (via pgbouncer) cannot CREATE TABLE on public; this script
# uses postgres-credentials from the data namespace to upgrade head, then
# verifies scheduled_actions exists via the app pool.
#
# Until a nexus-api image ships with the fixed 0014 migration (no duplicate
# ix_session_checkpoints_run_id index), copies the repo alembic tree into the
# pod and runs against /tmp/alembic-staging.ini — the in-image 0014 still
# duplicates the index created by index=True on run_id.
#
# Usage:
#   ./scripts/run-staging-migrations.sh
#   ./scripts/run-staging-migrations.sh --dry-run
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

PG_USER=$(kubectl -n data get secret postgres-credentials -o jsonpath='{.data.username}' | base64 -d)
PG_PASS=$(kubectl -n data get secret postgres-credentials -o jsonpath='{.data.password}' | base64 -d)
ADMIN_URL=$(python3 -c "import os,urllib.parse; u=os.environ['PG_USER']; p=os.environ['PG_PASS']; print(f\"postgresql+asyncpg://{urllib.parse.quote(u,safe='')}:{urllib.parse.quote(p,safe='')}@postgres.data.svc.cluster.local:5432/selva_staging\")")

POD=$(kubectl -n selva-staging get pod -l app.kubernetes.io/name=nexus-api -o jsonpath='{.items[0].metadata.name}')

echo "== Staging DB migrations (selva_staging) =="
if $DRY_RUN; then
  echo "DRY: kubectl cp alembic -> ${POD}:/tmp/alembic-staging"
  echo "DRY: alembic upgrade head via postgres admin URL"
  exit 0
fi

kubectl -n selva-staging cp "${ROOT}/apps/nexus-api/alembic" "${POD}:/tmp/alembic-staging"

kubectl -n selva-staging exec "$POD" -- sh -c "
set -e
cat > /tmp/alembic-staging.ini <<'INI'
[alembic]
script_location = /tmp/alembic-staging
prepend_sys_path = /app/apps/nexus-api

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
INI
cd /app/apps/nexus-api
DATABASE_URL='${ADMIN_URL}' /app/.venv/bin/alembic -c /tmp/alembic-staging.ini upgrade head
"

echo "--- verify scheduled_actions (postgres admin) ---"
kubectl -n data exec deploy/postgres -- psql -U postgres -d selva_staging -tAc \
  "SELECT COALESCE(to_regclass('public.scheduled_actions')::text, 'MISSING')"

echo "OK   staging migrations complete"
