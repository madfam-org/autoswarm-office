"""FastAPI application for the Selva inference gateway (RFC 0034 P2).

Deliberately MINIMAL — the whole point of the extraction is that this service's
uptime does not depend on the nexus-api monolith. It mounts the SAME
`inference_proxy` router nexus-api uses (single source of truth: routing,
pricing, and the USD usage ledger are not re-implemented), the SAME auth, and
the SAME database — but none of the orchestration / campaign / audit surface.

Middleware is the minimum the proxy needs: security headers, request id, and
the tenant-scoping context var the auth layer sets. No CSRF (this is a
service-to-service JSON API called with bearer tokens, not a browser surface),
no rate-limit middleware (Cloudflare + provider limits front it), no audit
middleware (usage is recorded by the ledger, and the activity event still fires
from the proxy).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexus_api.config import get_settings
from nexus_api.database import engine
from nexus_api.middleware.request_id import RequestIdMiddleware
from nexus_api.middleware.security import SecurityHeadersMiddleware
from nexus_api.routers import inference_proxy

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Verify the DB engine on startup (the ledger needs it); dispose on exit.

    Redis is intentionally NOT required — the gateway does not touch real-time
    room state; a Redis outage must not take the inference chokepoint down.
    """
    settings = get_settings()
    logger.info("Inference gateway starting on port %d", settings.port)
    async with engine.begin() as conn:
        await conn.run_sync(lambda _conn: None)
    logger.info("Database engine initialized (usage ledger ready)")
    yield
    await engine.dispose()
    logger.info("Inference gateway shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    _docs_enabled = settings.environment != "production"
    app = FastAPI(
        title="Selva Inference Gateway",
        version="0.1.0",
        description="OpenAI-compatible /v1 proxy — the ecosystem LLM chokepoint.",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if _docs_enabled else None,
        openapi_url="/api/v1/openapi.json" if _docs_enabled else None,
        redoc_url=None,
    )

    app.add_middleware(
        SecurityHeadersMiddleware,
        cors_origins=settings.cors_origins,
        csp_extra_sources=settings.csp_extra_sources,
    )
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "healthy", "service": "inference-gateway"}

    # The SAME router nexus-api serves at /v1 — mounted here as the primary
    # home. During the dual-run cutover both answer /v1; callers migrate their
    # SELVA_API_URL one at a time (see the cutover runbook), then nexus-api's
    # mount is removed.
    app.include_router(inference_proxy.router, prefix="/v1")

    return app


app = create_app()
