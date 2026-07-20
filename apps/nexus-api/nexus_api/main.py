"""FastAPI application factory for the Selva Nexus API."""

from __future__ import annotations

import hmac as hmac_mod
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
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
from .middleware.tracing import TraceContextMiddleware
from .operational_metrics import render_prometheus_metrics
from .routers import (
    admin,
    admin_consent,
    agents,
    analytics,
    approvals,
    artifacts,
    audit,
    audit_unified,
    billing,
    billing_internal,
    calendar,
    campaign_authorizations,
    campaigns,
    chat,
    checkpoints,
    command_approvals,
    convergence,
    crm_webhooks,
    departments,
    dragon_eggs,
    events,
    gateway,
    health,
    hitl_confidence,
    intelligence,
    invoices,
    maps,
    marketplace,
    metrics,
    onboarding,
    playbooks,
    probe,
    providers,
    scheduled_actions,
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
        title="Selva Nexus API",
        version="0.2.0",
        description="Core orchestration API for the Selva Office platform",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if _docs_enabled else None,
        redoc_url="/api/v1/redoc" if _docs_enabled else None,
        openapi_url="/api/v1/openapi.json" if _docs_enabled else None,
    )

    # -- Prometheus metrics ----------------------------------------------------
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app)
    except ImportError:
        pass  # prometheus-fastapi-instrumentator not installed

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(request: Request) -> Response:
        # /metrics enumerates the entire internal API surface (every route
        # path, method, and error rate) — useful reconnaissance for an
        # attacker. Prometheus scrapes over the in-cluster ClusterIP, which
        # does NOT traverse the Cloudflare tunnel, so a request bearing the
        # tunnel's edge headers is by definition public and is refused unless
        # it presents the service token. In-cluster scrapes (no CF headers)
        # pass unchanged, so the existing ServiceMonitors keep working.
        settings = get_settings()
        via_cloudflare = bool(
            request.headers.get("cf-connecting-ip") or request.headers.get("cf-ray")
        )
        if via_cloudflare:
            auth = request.headers.get("authorization", "")
            token = auth[7:] if auth.lower().startswith("bearer ") else ""
            token_ok = (
                settings.worker_api_token
                and settings.worker_api_token != "dev-bypass"
                and hmac_mod.compare_digest(token, settings.worker_api_token)
            )
            if not token_ok:
                return Response(status_code=404)
        body, content_type = await render_prometheus_metrics()
        return Response(content=body, media_type=content_type)

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
    # TraceContextMiddleware MUST be added AFTER RequestIdMiddleware so it
    # runs BEFORE it on inbound requests (Starlette middleware stack is
    # LIFO on the request path). This way the W3C parent context is
    # attached before RequestIdMiddleware reads the current span to format
    # the outgoing ``traceparent`` response header.
    app.add_middleware(TraceContextMiddleware)
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
    app.include_router(billing.webhook_router, prefix="/api/v1/billing")
    app.include_router(billing_internal.router, prefix="/api/v1/billing")
    app.include_router(skills.router, prefix="/api/v1/skills")
    # Harness communication gateway canonical routes:
    # /api/v1/gateway/<channel>/...
    app.include_router(gateway.router, prefix="/api/v1")
    # Backward-compatible legacy routes for previously registered webhooks:
    # /api/v1/gateway/gateway/<channel>/...
    app.include_router(gateway.router, prefix="/api/v1/gateway", include_in_schema=False)
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
    # Convergence read surface for converge-dash (RFC 0034 P1b / D7).
    app.include_router(convergence.router, prefix="/api/v1/convergence")
    app.include_router(admin.router, prefix="/api/v1/admin")
    # Per-period HMAC key tracking for the consent ledger (migration 0030).
    # Endpoint at /api/v1/admin/consent-ledger/promote-key — requires
    # admin OR platform role.
    app.include_router(admin_consent.router, prefix="/api/v1")
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
    app.include_router(scheduled_actions.router, prefix="/api/v1")
    # Dragon-egg social-account hatching (Phase 1, admin-only).
    app.include_router(dragon_eggs.router, prefix="/api/v1")
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
    # Phase 2: Tulana SKU campaign import + planning
    app.include_router(campaigns.router, prefix="/api/v1")
    app.include_router(campaign_authorizations.router, prefix="/api/v1")
    # Stripe webhook (Phase 1 scaffold) — signature verification today;
    # per-event handlers land in follow-up PRs as each event becomes
    # operationally relevant per ROADMAP Phase 2.
    app.include_router(stripe_webhooks.router, prefix="/api/v1")
    # Revenue-loop probe (A.7): bearer-auth'd + public /latest-run endpoint.
    app.include_router(probe.router, prefix="/api/v1/probe")
    # LLM provider balance probe — admin endpoint surfacing cached balances
    # so ops doesn't have to log into the Anthropic console manually to
    # discover we're at $0. Closes the visibility gap left by the
    # 2026-04-16 incident.
    app.include_router(providers.router, prefix="/api/v1")
    # HITL Confidence (Sprint 1 observe-only) — decisions ledger + dashboard
    app.include_router(hitl_confidence.router, prefix="/api/v1")

    # -- OpenAI-compatible inference proxy (ecosystem LLM gateway) -------------
    # The OpenAI-compatible /v1 inference proxy moved to its own deployable,
    # apps/inference-gateway (inference.selva.town) — RFC 0034 P2, cutover
    # completed 2026-07-07. The router lives on in .routers.inference_proxy,
    # mounted ONLY by the gateway.

    # -- A2A Protocol (agent-to-agent discovery and task exchange) -------------
    try:
        from selva_a2a import AgentSkill, create_a2a_router
        from selva_a2a.schema import TaskRequest as A2ATaskRequest
        from selva_a2a.schema import TaskResponse as A2ATaskResponse
        from selva_a2a.schema import TaskStatus as A2ATaskStatus

        async def _dispatch_a2a_task(req: A2ATaskRequest) -> str:
            """Bridge an inbound A2A task into the internal dispatch pipeline.

            A2A tasks live in the synthetic ``"a2a-external"`` org. Use
            ``tenant_session`` so RLS Phase 1.5 strict mode honours the
            INSERT — bare ``async_session_factory()`` left
            ``app.current_org_id`` unset, which the strict policy would
            reject. See ``docs/RLS_PHASE_1_5_AUDIT.md`` §2.E.
            """
            from .database import tenant_session
            from .models import SwarmTask

            async with tenant_session(org_id="a2a-external") as db:
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
                        "xadd", "selva:task-stream", {"data": task_msg}
                    )
                except Exception:
                    task.status = "pending"
                    await db.flush()

                await db.commit()
                return task_id

        async def _get_a2a_task_status(task_id: str) -> A2ATaskResponse:
            """Look up internal task status for an A2A caller.

            Same RLS Phase 1.5 fix as ``_dispatch_a2a_task`` — A2A tasks
            are in the ``"a2a-external"`` org so the SELECT must run
            with ``app.current_org_id="a2a-external"`` to find them
            once strict policies are enabled.
            """
            import uuid as _uuid

            from sqlalchemy import select

            from .database import tenant_session
            from .models import SwarmTask

            try:
                uid = _uuid.UUID(task_id)
            except ValueError:
                return A2ATaskResponse(
                    task_id=task_id,
                    status=A2ATaskStatus.FAILED,
                    error="Invalid task ID",
                )

            async with tenant_session(org_id="a2a-external") as db:
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
                # SkillMetadata has no `tags` attribute — AgentSkill.tags
                # defaults to []. If we ever add tags to SkillMetadata,
                # plumb it through here.
                return [
                    AgentSkill(
                        id=s.name,
                        name=s.name,
                        description=s.description,
                    )
                    for s in registry.list_skills()
                ]
            except Exception:
                return []

        a2a_router = create_a2a_router(
            agent_name="Selva Office",
            base_url=settings.public_app_url,
            get_skills=_get_a2a_skills,
            dispatch_task=_dispatch_a2a_task,
            get_task_status=_get_a2a_task_status,
        )
        app.include_router(a2a_router, prefix="/api/v1")
        logger.info("A2A protocol router mounted at /api/v1/a2a")
    except ImportError:
        logger.debug("selva-a2a not installed; A2A protocol disabled")

    return app


# Module-level app instance for ``uvicorn nexus_api.main:app``.
app = create_app()
