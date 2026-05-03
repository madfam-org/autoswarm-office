"""FastAPI application factory for the AutoSwarm Nexus API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from selva_observability import init_sentry, init_tracing
from selva_redis_pool import get_redis_pool

from .analytics import init_posthog
from .analytics import shutdown as shutdown_posthog
from .config import get_settings
from .database import engine
from .logging_config import configure_logging
from .middleware.audit import AuditMiddleware
from .middleware.csrf import CSRFMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_id import RequestIdMiddleware
from .middleware.security import SecurityHeadersMiddleware, TenantRLSMiddleware
from .routers import (
    admin,
    agents,
    analytics,
    approvals,
    artifacts,
    audit,
    audit_unified,
    billing,
    billing_internal,
    calendar,
    chat,
    checkpoints,
    command_approvals,
    crm_webhooks,
    departments,
    events,
    gateway,
    health,
    hitl_confidence,
    inference_proxy,
    intelligence,
    invoices,
    maps,
    marketplace,
    metrics,
    onboarding,
    playbooks,
    probe,
    schedules,
    skills,
    skills_hub,
    stripe_webhooks,
    swarms,
    tenant_identities,
    tenants,
    trajectories,
    voice,
    workflows,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Initializes the async database engine, Redis pool, and verifies
    connectivity on startup, then disposes resources on shutdown.
    """
    settings = get_settings()

    # -- Startup --------------------------------------------------------------
    init_posthog()
    logger.info("Nexus API starting on port %d", settings.port)

    # Verify database engine connectivity.
    async with engine.begin() as conn:
        await conn.run_sync(lambda _conn: None)  # connection check
    logger.info("Database engine initialized")

    # Initialize Redis pool and verify connectivity.
    pool = get_redis_pool(url=settings.redis_url)
    if await pool.ping():
        logger.info("Redis pool initialized and connection verified")
    else:
        logger.warning("Redis unavailable at startup; real-time features may be degraded")

    yield

    # -- Shutdown -------------------------------------------------------------
    shutdown_posthog()
    await pool.close()
    await engine.dispose()
    logger.info("Nexus API shut down")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    configure_logging(settings.log_format)
    init_sentry("nexus-api")
    init_tracing("nexus-api")
    logger.info("Configuration validated for environment=%s", settings.environment)

    # H9 (audit 2026-04-23): /docs and /openapi.json must NOT be public in
    # prod (would enumerate every nexus-api endpoint to anonymous callers).
    # Gate on settings.environment so local/staging keep Swagger UI.
    _docs_enabled = settings.environment != "production"
    app = FastAPI(
        title="AutoSwarm Nexus API",
        version="0.2.0",
        description="Core orchestration API for the AutoSwarm Office platform",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if _docs_enabled else None,
        redoc_url="/api/v1/redoc" if _docs_enabled else None,
        openapi_url="/api/v1/openapi.json" if _docs_enabled else None,
    )

    # -- Prometheus metrics ----------------------------------------------------
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    except ImportError:
        pass  # prometheus-fastapi-instrumentator not installed

    # -- CORS -----------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )

    # -- Middleware stack (outermost first) ------------------------------------
    app.add_middleware(
        SecurityHeadersMiddleware,
        cors_origins=settings.cors_origins,
        csp_extra_sources=settings.csp_extra_sources,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(TenantRLSMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        redis_url=settings.redis_url,
        requests_per_minute=settings.rate_limit_per_minute,
    )
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(AuditMiddleware)

    # -- Root health endpoint (K8s liveness probe) ----------------------------
    @app.get("/health", tags=["health"])
    async def root_health() -> dict[str, str]:
        return {"status": "healthy", "service": "nexus-api"}

    # -- Routers --------------------------------------------------------------
    app.include_router(health.router, prefix="/api/v1/health")
    app.include_router(agents.router, prefix="/api/v1/agents")
    app.include_router(departments.router, prefix="/api/v1/departments")
    app.include_router(approvals.router, prefix="/api/v1/approvals")
    app.include_router(swarms.router, prefix="/api/v1/swarms")
    app.include_router(billing.router, prefix="/api/v1/billing")
    app.include_router(billing_internal.router, prefix="/api/v1/billing")
    app.include_router(skills.router, prefix="/api/v1/skills")
    app.include_router(gateway.router, prefix="/api/v1/gateway")
    app.include_router(workflows.router, prefix="/api/v1/workflows")
    app.include_router(artifacts.router, prefix="/api/v1/artifacts")
    app.include_router(marketplace.router, prefix="/api/v1/marketplace")
    app.include_router(maps.router, prefix="/api/v1/maps")
    app.include_router(calendar.router, prefix="/api/v1/calendar")
    app.include_router(intelligence.router, prefix="/api/v1/intelligence")
    app.include_router(invoices.router, prefix="/api/v1/invoices")
    app.include_router(chat.router, prefix="/api/v1/chat")
    app.include_router(events.router, prefix="/api/v1/events")
    app.include_router(metrics.router, prefix="/api/v1/metrics")
    app.include_router(admin.router, prefix="/api/v1/admin")
    app.include_router(audit.router, prefix="/api/v1/audit")
    # Cross-service unified view over the 4 Selva RFC ledgers. Separate
    # from the middleware-row ``audit`` router above because the two
    # tables have different schemas and different RBAC semantics.
    app.include_router(audit_unified.router, prefix="/api/v1/audit/unified")
    app.include_router(analytics.router, prefix="/api/v1/analytics")
    app.include_router(tenants.router, prefix="/api/v1/tenants")
    app.include_router(tenant_identities.router, prefix="/api/v1")
    app.include_router(voice.router, prefix="/api/v1/voice")
    # Outbound voice mode + consent ledger (migration 0018).
    # Mounted at /api/v1 so both /onboarding/* and /settings/outbound-voice
    # routes live on the canonical top-level paths.
    app.include_router(onboarding.router, prefix="/api/v1")
    app.include_router(schedules.router, prefix="/api/v1")
    # Gap 2: Dangerous command approval
    app.include_router(command_approvals.router, prefix="/api/v1")
    # Gap 6: ShareGPT trajectory export
    app.include_router(trajectories.router, prefix="/api/v1")
    # Next-tier: Session checkpoint/rollback
    app.include_router(checkpoints.router, prefix="/api/v1")
    app.include_router(skills_hub.router, prefix="/api/v1")  # Track D1: agentskills.io hub
    # Autonomous operations (Swarm Manifesto)
    app.include_router(playbooks.router, prefix="/api/v1")
    app.include_router(crm_webhooks.router, prefix="/api/v1")
    # Stripe webhook (Phase 1 scaffold) — signature verification today;
    # per-event handlers land in follow-up PRs as each event becomes
    # operationally relevant per ROADMAP Phase 2.
    app.include_router(stripe_webhooks.router, prefix="/api/v1")
    # Revenue-loop probe (A.7): bearer-auth'd + public /latest-run endpoint.
    app.include_router(probe.router, prefix="/api/v1/probe")
    # HITL Confidence (Sprint 1 observe-only) — decisions ledger + dashboard
    app.include_router(hitl_confidence.router, prefix="/api/v1")

    # -- OpenAI-compatible inference proxy (ecosystem LLM gateway) -------------
    app.include_router(inference_proxy.router, prefix="/v1")

    # -- A2A Protocol (agent-to-agent discovery and task exchange) -------------
    try:
        from selva_a2a import AgentSkill, create_a2a_router
        from selva_a2a.schema import TaskRequest as A2ATaskRequest
        from selva_a2a.schema import TaskResponse as A2ATaskResponse
        from selva_a2a.schema import TaskStatus as A2ATaskStatus

        async def _dispatch_a2a_task(req: A2ATaskRequest) -> str:
            """Bridge an inbound A2A task into the internal dispatch pipeline."""
            from .database import async_session_factory
            from .models import SwarmTask

            async with async_session_factory() as db:
                task = SwarmTask(
                    description=req.description,
                    graph_type=req.graph_type,
                    payload=req.metadata,
                    status="queued",
                    org_id="a2a-external",
                )
                db.add(task)
                await db.flush()
                await db.refresh(task)
                task_id = str(task.id)

                # Enqueue to Redis
                try:
                    import json as _json

                    pool = get_redis_pool(url=settings.redis_url)
                    task_msg = _json.dumps(
                        {
                            "task_id": task_id,
                            "graph_type": task.graph_type,
                            "description": task.description,
                            "assigned_agent_ids": [],
                            "required_skills": [],
                            "payload": task.payload or {},
                        }
                    )
                    await pool.execute_with_retry(
                        "xadd", "autoswarm:task-stream", {"data": task_msg}
                    )
                except Exception:
                    task.status = "pending"
                    await db.flush()

                await db.commit()
                return task_id

        async def _get_a2a_task_status(task_id: str) -> A2ATaskResponse:
            """Look up internal task status for an A2A caller."""
            import uuid as _uuid

            from sqlalchemy import select

            from .database import async_session_factory
            from .models import SwarmTask

            try:
                uid = _uuid.UUID(task_id)
            except ValueError:
                return A2ATaskResponse(
                    task_id=task_id,
                    status=A2ATaskStatus.FAILED,
                    error="Invalid task ID",
                )

            async with async_session_factory() as db:
                result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
                task = result.scalar_one_or_none()

            if task is None:
                return A2ATaskResponse(
                    task_id=task_id,
                    status=A2ATaskStatus.FAILED,
                    error="Task not found",
                )

            status_map = {
                "queued": A2ATaskStatus.PENDING,
                "pending": A2ATaskStatus.PENDING,
                "running": A2ATaskStatus.RUNNING,
                "completed": A2ATaskStatus.COMPLETED,
                "failed": A2ATaskStatus.FAILED,
                "cancelled": A2ATaskStatus.FAILED,
            }
            return A2ATaskResponse(
                task_id=task_id,
                status=status_map.get(task.status, A2ATaskStatus.PENDING),
                result=task.payload if task.status == "completed" else None,
                error=task.error_message if task.status == "failed" else None,
            )

        def _get_a2a_skills() -> list[AgentSkill]:
            """Advertise registered skills in the AgentCard."""
            try:
                from selva_skills import get_skill_registry

                registry = get_skill_registry()
                return [
                    AgentSkill(
                        id=s.name,
                        name=s.name,
                        description=s.description,
                        tags=s.tags,
                    )
                    for s in registry.list_skills()
                ]
            except Exception:
                return []

        a2a_router = create_a2a_router(
            agent_name="Selva Office",
            base_url=settings.cors_origins[0] if settings.cors_origins else "",
            get_skills=_get_a2a_skills,
            dispatch_task=_dispatch_a2a_task,
            get_task_status=_get_a2a_task_status,
        )
        app.include_router(a2a_router, prefix="/api/v1")
        logger.info("A2A protocol router mounted at /api/v1/a2a")
    except ImportError:
        logger.debug("autoswarm-a2a not installed; A2A protocol disabled")

    return app


# Module-level app instance for ``uvicorn nexus_api.main:app``.
app = create_app()
