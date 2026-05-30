#!/usr/bin/env bash
# Break-glass drain of staging Redis task stream backlog (pre–load-test calibration).
#
# Trims autoswarm:task-stream, clears DLQ, and fails queued/running DB rows so
# Run 3 k6 starts from a clean slate. Staging only.
#
# Usage:
#   ./scripts/drain-staging-task-queue.sh --dry-run
#   ./scripts/drain-staging-task-queue.sh
#
set -euo pipefail

NS="${STAGING_NAMESPACE:-autoswarm-staging}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

echo "== Drain staging task queue (namespace=${NS}) =="

if ! command -v kubectl >/dev/null 2>&1; then
  echo "FAIL: kubectl required"
  exit 1
fi

if $DRY_RUN; then
  echo "DRY: would trim Redis stream + fail queued/running swarm_tasks in ${NS}"
  exit 0
fi

kubectl -n "$NS" exec -i deploy/nexus-api -- python3 - <<'PY'
import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import text

from nexus_api.database import admin_session
from selva_redis_pool import get_redis_pool


async def drain_redis() -> None:
    pool = get_redis_pool(url=os.environ["REDIS_URL"])
    client = await pool.client()
    stream = "autoswarm:task-stream"
    dlq = "autoswarm:task-dlq"
    before = await client.xlen(stream)
    dlq_before = await client.xlen(dlq)
    await client.xtrim(stream, maxlen=0, approximate=False)
    await client.xtrim(dlq, maxlen=0, approximate=False)
    # Reset consumer group PEL (orphaned after trim).
    try:
        await client.xgroup_destroy(stream, "autoswarm-workers")
    except Exception:
        pass
    try:
        await client.xgroup_create(stream, "autoswarm-workers", id="0", mkstream=True)
    except Exception:
        pass
    after = await client.xlen(stream)
    dlq_after = await client.xlen(dlq)
    print(f"OK: trimmed {stream} {before} -> {after}")
    print(f"OK: trimmed {dlq} {dlq_before} -> {dlq_after}")


async def fail_open_tasks() -> None:
    async with admin_session() as db:
        result = await db.execute(
            text(
                """
                UPDATE swarm_tasks
                SET status = 'failed',
                    updated_at = :now,
                    completed_at = :now
                WHERE status IN ('queued', 'pending', 'running')
                """
            ),
            {"now": datetime.now(UTC)},
        )
        print(f"OK: marked {result.rowcount} swarm_tasks failed (queued/pending/running)")


async def main() -> None:
    await drain_redis()
    await fail_open_tasks()


asyncio.run(main())
PY

TOKEN="$(kubectl -n "$NS" get secret autoswarm-staging-secrets \
  -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
if [[ -n "$TOKEN" ]]; then
  curl -sf -X POST "https://staging-api.selva.town/api/v1/swarms/tasks/reap-stale" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Selva-Tenant-Org: madfam" >/dev/null 2>&1 || true
fi

curl -sf -H "Authorization: Bearer ${TOKEN}" -H "X-Selva-Tenant-Org: madfam" \
  "https://staging-api.selva.town/api/v1/health/queue-stats" | python3 -m json.tool 2>/dev/null || true

echo "OK   staging queue drain complete"
