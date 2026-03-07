"""Health and readiness probe endpoints."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from ..config import get_settings
from ..database import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_settings = get_settings()


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
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(_settings.redis_url, decode_responses=True)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "ok"
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
    """Detailed health check including Colyseus connectivity."""
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
    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(_settings.redis_url, decode_responses=True)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        checks["redis"] = "unavailable"

    # -- Colyseus check -------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:4303/health")
            checks["colyseus"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["colyseus"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if all_ok else "degraded",
        "version": "0.1.0",
        "service": "nexus-api",
        "checks": checks,
    }
