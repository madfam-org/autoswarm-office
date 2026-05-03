"""Health and readiness probe endpoints."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..config import get_settings
from ..database import async_session_factory, get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_settings = get_settings()

# Application role name whose privileges on `consent_ledger` we expect to
# enforce the append-only invariant. Migration 0018 REVOKEs UPDATE/DELETE
# from this role. Configurable via env in case a deployment uses a
# different app role name.
_CONSENT_LEDGER_APP_ROLE = os.environ.get("CONSENT_LEDGER_APP_ROLE", "autoswarm_app")

# How many most-recent DLQ entries the /dlq-stats endpoint returns. Bounded
# so the JSON response stays small; ops dashboards can paginate via
# repeated calls if a deeper history is ever needed.
_DLQ_RECENT_LIMIT: int = 10


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe -- always returns 200 if the process is running."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "service": "nexus-api",
    }


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """Readiness probe -- validates database and Redis connectivity.

    Returns 200 when all dependencies are reachable, 503 otherwise.
    """
    checks: dict[str, str] = {}

    # -- Database check -------------------------------------------------------
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Database readiness check failed: %s", exc)
        checks["database"] = "unavailable"

    # -- Redis check ----------------------------------------------------------
    try:
        pool = get_redis_pool(url=_settings.redis_url)
        if await pool.ping():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
    except Exception as exc:
        logger.error("Redis readiness check failed: %s", exc)
        checks["redis"] = "unavailable"

    # -- Aggregate result -----------------------------------------------------
    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/detail")
async def health_detail(response: Response) -> dict[str, object]:
    """Detailed health check including Colyseus connectivity and pool metrics."""
    checks: dict[str, str] = {}

    # -- Database check -------------------------------------------------------
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        checks["database"] = "unavailable"

    # -- Redis check ----------------------------------------------------------
    pool = get_redis_pool(url=_settings.redis_url)
    try:
        if await pool.ping():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        checks["redis"] = "unavailable"

    # -- Colyseus check -------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            _colyseus_url = os.environ.get("COLYSEUS_URL", "http://localhost:4303")
            resp = await client.get(f"{_colyseus_url}/health")
            checks["colyseus"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        logger.debug("Colyseus health check failed", exc_info=True)
        checks["colyseus"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if all_ok else "degraded",
        "version": "0.1.0",
        "service": "nexus-api",
        "checks": checks,
        "redis_pool": pool.metrics(),
    }


@router.get("/pool-stats")
async def pool_stats() -> dict[str, object]:
    """Return database connection pool statistics."""
    from sqlalchemy.pool import QueuePool

    from ..database import get_engine

    eng = get_engine()
    pool = eng.pool
    if not isinstance(pool, QueuePool):
        return {"error": "pool is not a QueuePool", "status": pool.status()}
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "invalid": pool.status(),
    }


@router.get("/queue-stats")
async def queue_stats() -> dict[str, object]:
    """Return Redis task stream and queue statistics."""
    pool = get_redis_pool(url=_settings.redis_url)
    stats: dict[str, object] = {}

    try:
        client = await pool.client()

        # Stream length
        try:
            stats["stream_length"] = await client.xlen("autoswarm:task-stream")
        except Exception:
            logger.debug("Failed to fetch stream length", exc_info=True)
            stats["stream_length"] = 0

        # DLQ depth
        try:
            stats["dlq_depth"] = await client.xlen("autoswarm:task-dlq")
        except Exception:
            logger.debug("Failed to fetch DLQ depth", exc_info=True)
            stats["dlq_depth"] = 0

        # Consumer group info
        try:
            groups = await client.xinfo_groups("autoswarm:task-stream")
            stats["consumer_groups"] = [
                {
                    "name": g.get("name", ""),
                    "consumers": g.get("consumers", 0),
                    "pending": g.get("pending", 0),
                    "last_delivered_id": g.get("last-delivered-id", ""),
                }
                for g in groups
            ]
        except Exception:
            logger.debug("Failed to fetch consumer group info", exc_info=True)
            stats["consumer_groups"] = []

    except Exception as exc:
        logger.warning("Failed to fetch queue stats: %s", exc)
        stats["error"] = str(exc)

    stats["redis_pool"] = pool.metrics()
    return stats


@router.get("/dlq-stats")
async def dlq_stats() -> dict[str, object]:
    """Return dead-letter queue statistics and recent entries."""
    pool = get_redis_pool(url=_settings.redis_url)
    result: dict[str, object] = {}

    try:
        client = await pool.client()

        try:
            result["depth"] = await client.xlen("autoswarm:task-dlq")
        except Exception:
            logger.debug("Failed to fetch DLQ depth", exc_info=True)
            result["depth"] = 0

        # Return the N most recent DLQ entries (see _DLQ_RECENT_LIMIT).
        try:
            entries = await client.xrevrange(
                "autoswarm:task-dlq", count=_DLQ_RECENT_LIMIT
            )
            result["recent"] = [{"id": eid, "data": data} for eid, data in entries]
        except Exception:
            logger.debug("Failed to fetch recent DLQ entries", exc_info=True)
            result["recent"] = []

    except Exception as exc:
        logger.warning("Failed to fetch DLQ stats: %s", exc)
        result["error"] = str(exc)

    return result


@router.get("/consent-ledger-grants")
async def consent_ledger_grants(
    response: Response,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Verify the append-only invariant on `consent_ledger` is enforced at the DB level.

    Migration 0018 REVOKEs UPDATE/DELETE on `consent_ledger` from the
    application role (default ``autoswarm_app``). This endpoint exposes
    a runtime check so a re-applied migration, manual ``GRANT ALL``, or
    a superuser-mode test seed that silently re-mutates the grants will
    surface in monitoring.

    Open endpoint (no auth) — matches the rest of `/health`. The role
    name is not echoed in the response to avoid disclosing internal
    config; it is logged when the invariant fails for ops triage.

    Returns 503 when the invariant does not hold.
    """
    role = _CONSENT_LEDGER_APP_ROLE
    body: dict[str, Any] = {
        "invariant_holds": False,
        "can_insert": None,
        "can_update": None,
        "can_delete": None,
    }

    try:
        result = await db.execute(
            text(
                """
                SELECT
                    has_table_privilege(:role, 'consent_ledger', 'INSERT') AS can_insert,
                    has_table_privilege(:role, 'consent_ledger', 'UPDATE') AS can_update,
                    has_table_privilege(:role, 'consent_ledger', 'DELETE') AS can_delete
                """
            ),
            {"role": role},
        )
        row = result.one()
    except Exception as exc:
        # Most common case: SQLite test DB or PostgreSQL role doesn't
        # exist (dev setups). Surface as degraded rather than crashing.
        logger.warning(
            "Consent ledger grant probe failed (role=%s): %s", role, exc
        )
        body["error"] = "grant_probe_unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return body

    can_insert = bool(row.can_insert)
    can_update = bool(row.can_update)
    can_delete = bool(row.can_delete)

    invariant_holds = can_insert and not can_update and not can_delete

    body["invariant_holds"] = invariant_holds
    body["can_insert"] = can_insert
    body["can_update"] = can_update
    body["can_delete"] = can_delete

    if not invariant_holds:
        # Log role name for ops; do not return it in the body.
        logger.error(
            "Consent ledger append-only invariant VIOLATED -- "
            "role=%s INSERT=%s UPDATE=%s DELETE=%s",
            role,
            can_insert,
            can_update,
            can_delete,
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return body
