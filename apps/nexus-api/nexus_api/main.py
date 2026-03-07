"""FastAPI application factory for the AutoSwarm Nexus API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import engine
from .logging_config import configure_logging
from .middleware.csrf import CSRFMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_id import RequestIdMiddleware
from .middleware.security import SecurityHeadersMiddleware
from .routers import agents, approvals, billing, departments, gateway, health, skills, swarms

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Initializes the async database engine and verifies Redis connectivity
    on startup, then disposes resources on shutdown.
    """
    settings = get_settings()

    # -- Startup --------------------------------------------------------------
    logger.info("Nexus API starting on port %d", settings.port)

    # Verify database engine connectivity.
    async with engine.begin() as conn:
        await conn.run_sync(lambda _conn: None)  # connection check
    logger.info("Database engine initialized")

    # Verify Redis connectivity.
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
        logger.info("Redis connection verified")
    except Exception:
        logger.warning("Redis unavailable at startup; real-time features may be degraded")
    finally:
        await redis_client.aclose()

    yield

    # -- Shutdown -------------------------------------------------------------
    await engine.dispose()
    logger.info("Nexus API shut down")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    configure_logging(settings.log_format)

    app = FastAPI(
        title="AutoSwarm Nexus API",
        version="0.1.0",
        description="Core orchestration API for the AutoSwarm Office platform",
        lifespan=lifespan,
    )

    # -- CORS -----------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )

    # -- Middleware stack (outermost first) ------------------------------------
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        redis_url=settings.redis_url,
        requests_per_minute=settings.rate_limit_per_minute,
    )
    app.add_middleware(CSRFMiddleware)

    # -- Routers --------------------------------------------------------------
    app.include_router(health.router, prefix="/api/v1/health")
    app.include_router(agents.router, prefix="/api/v1/agents")
    app.include_router(departments.router, prefix="/api/v1/departments")
    app.include_router(approvals.router, prefix="/api/v1/approvals")
    app.include_router(swarms.router, prefix="/api/v1/swarms")
    app.include_router(billing.router, prefix="/api/v1/billing")
    app.include_router(skills.router, prefix="/api/v1/skills")
    app.include_router(gateway.router, prefix="/api/v1/gateway")

    return app


# Module-level app instance for ``uvicorn nexus_api.main:app``.
app = create_app()
