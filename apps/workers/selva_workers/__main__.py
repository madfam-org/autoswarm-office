"""AutoSwarm worker process -- Redis Streams consumer for LangGraph execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cachetools import TTLCache
from langgraph.types import Command

from selva_observability import (
    bind_task_context,
    clear_context,
    configure_logging,
    init_sentry,
    init_tracing,
)
from selva_permissions import resolve_audience
from selva_redis_pool import get_redis_pool
from selva_redis_pool.task_stream import (
    MAX_RETRIES,
    TaskStreamConsumer,
)
from selva_redis_pool.timeout import get_task_timeout
from selva_tools import Audience as ToolAudience
from selva_tools import with_audience

from .checkpointer import close_checkpointer, create_checkpointer
from .config import get_settings
from .event_emitter import emit_event as _emit_event
from .graphs.accounting import build_accounting_graph
from .graphs.billing import build_billing_graph
from .graphs.coding import build_coding_graph
from .graphs.crm import build_crm_graph
from .graphs.deployment import build_deployment_graph
from .graphs.intelligence import build_intelligence_graph
from .graphs.meeting import build_meeting_graph
from .graphs.operations import build_operations_graph
from .graphs.project import build_project_graph
from .graphs.puppeteer import build_puppeteer_graph
from .graphs.research import build_research_graph
from .graphs.sales import build_sales_graph
from .interrupt_handler import InterruptHandler
from .task_status import update_task_status as _update_task_status

# Use shared observability logging instead of basicConfig.
configure_logging(service_name="worker")
init_sentry("worker")
init_tracing("worker")

logger = logging.getLogger("autoswarm.worker")

AGENT_STATUS_CHANNEL = "autoswarm:agent-status"
GRAPH_BUILDERS = {
    "accounting": build_accounting_graph,
    "billing": build_billing_graph,
    "coding": build_coding_graph,
    "research": build_research_graph,
    "crm": build_crm_graph,
    "deployment": build_deployment_graph,
    "intelligence": build_intelligence_graph,
    "operations": build_operations_graph,
    "puppeteer": build_puppeteer_graph,
    "meeting": build_meeting_graph,
    "project": build_project_graph,
    "sales": build_sales_graph,
    # "custom" is handled dynamically via WorkflowCompiler — see process_task()
}

checkpointer = create_checkpointer()

_shutdown = asyncio.Event()

# -- Module-internal constants -------------------------------------------------
# TTL (seconds) for the agent skill / role caches. Short-lived because
# per-agent skill changes from the API need to propagate within ~1 min.
_AGENT_CACHE_TTL_S: int = 60
# Capacity for the per-process agent caches. Sized for one orchestrator
# pod plus headroom; bump alongside agent count if eviction warnings appear.
_AGENT_CACHE_MAXSIZE: int = 256
# Seconds in one hour — used both as a multiplier (stale_hours → seconds)
# and as the periodic worktree-cleanup interval.
_SECONDS_PER_HOUR: int = 3600
_OUTBOX_MAX_BACKOFF_SECONDS: int = 60
_OUTBOX_ERROR_MAX_LENGTH: int = 2000

# Agent skill cache: avoids HTTP GET per task (Phase 4.2)
_skill_cache: TTLCache[str, list[str]] = TTLCache(
    maxsize=_AGENT_CACHE_MAXSIZE, ttl=_AGENT_CACHE_TTL_S
)
# Agent role cache: populated alongside skills for learning hooks
_role_cache: TTLCache[str, str] = TTLCache(
    maxsize=_AGENT_CACHE_MAXSIZE, ttl=_AGENT_CACHE_TTL_S
)


def _handle_signal(sig: signal.Signals) -> None:
    logger.info("Received %s, shutting down...", sig.name)
    _shutdown.set()


def _state_str(state: dict, key: str, default: str = "") -> str:
    """Read a string field from a loosely-typed graph state dict.

    Graph state dicts are runtime ``dict[Any, Any]`` so ``state.get(key)``
    statically resolves to ``object``. This helper preserves runtime behaviour
    while satisfying mypy strict mode at the call site. Coerces non-string
    values to ``str`` so downstream APIs that require ``str`` don't blow up
    on accidental ints, but treats missing keys / ``None`` as ``default``.
    """
    value = state.get(key)
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def _state_dict(state: dict, key: str) -> dict | None:
    """Read an optional dict field from a loosely-typed graph state dict.

    Returns ``None`` for missing keys, ``None`` values, or non-dict values
    so callers that expect ``dict | None`` (e.g. ``update_task_status``'s
    ``result`` parameter) don't receive a stray scalar.
    """
    value = state.get(key)
    return value if isinstance(value, dict) else None


async def run_graph_with_interrupts(
    compiled,  # noqa: ANN001 -- compiled LangGraph
    initial_state: dict,
    task_id: str,
    agent_id: str,
    handler: InterruptHandler,
) -> dict:
    """Invoke a compiled graph, handling any LangGraph interrupt() pauses.

    The loop:
    1. Invoke the graph (or resume it).
    2. Check ``graph.get_state(config).next`` for pending nodes.
    3. If there are pending nodes, inspect ``state.tasks[0].interrupts`` for
       the interrupt payload, create an approval request, wait for a decision,
       and resume with a ``Command(resume=...)``.
    4. Repeat until the graph finishes (``state.next`` is empty).

    Returns:
        The final graph state dict.
    """
    config = {"configurable": {"thread_id": task_id}}

    # First invocation.
    result = await asyncio.to_thread(compiled.invoke, initial_state, config)

    while True:
        snapshot = compiled.get_state(config)
        if not snapshot.next:
            break

        # There are pending nodes -- look for interrupt payloads.
        interrupt_value = None
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_value = snapshot.tasks[0].interrupts[0].value

        logger.info(
            "Task %s interrupted at node(s) %s with payload: %s",
            task_id,
            snapshot.next,
            interrupt_value,
        )

        # Build approval context from the interrupt payload.
        action_category = "api_call"
        payload: dict = {"task_id": task_id}
        reasoning = f"Agent {agent_id} requires approval during task {task_id}."

        if isinstance(interrupt_value, dict):
            action_category = interrupt_value.get("action_category", action_category)
            payload.update(interrupt_value)
            reasoning = interrupt_value.get("reasoning", reasoning)

        request_id = await handler.create_approval_request(
            agent_id=agent_id,
            action_category=action_category,
            payload=payload,
            reasoning=reasoning,
        )

        # Notify Colyseus that this agent is awaiting human approval.
        await _publish_agent_status(agent_id, "waiting_approval")

        approval = await handler.wait_for_approval(request_id)

        resume_value = {
            "approved": approval.result == "approved",
            "feedback": approval.feedback,
        }
        logger.info(
            "Resuming task %s after approval %s (approved=%s)",
            task_id,
            request_id,
            resume_value["approved"],
        )

        result = await asyncio.to_thread(compiled.invoke, Command(resume=resume_value), config)

    return result


async def _publish_agent_status(
    agent_id: str,
    new_status: str,
    current_node_id: str | None = None,
) -> None:
    """Publish an agent status change to Redis for Colyseus consumption."""
    if agent_id == "unknown":
        return
    try:
        pool = get_redis_pool()
        payload: dict[str, str] = {"agent_id": agent_id, "status": new_status}
        if current_node_id is not None:
            payload["current_node_id"] = current_node_id
        await pool.execute_with_retry(
            "publish",
            AGENT_STATUS_CHANNEL,
            json.dumps(payload),
        )
    except Exception:
        logger.warning("Failed to publish agent status for %s", agent_id)


async def _fetch_agent_skills(
    nexus_url: str, agent_id: str, org_id: str | None = None
) -> list[str]:
    """GET /api/v1/agents/{agent_id} and return effective_skills (cached).

    org_id is threaded into the X-Selva-Tenant-Org header so nexus-api
    resolves the worker token to the correct tenant. Without it, the
    call resolves to platform scope and may fail tenant-scoped reads.
    """
    if agent_id == "unknown":
        return []

    # Check cache first
    cached = _skill_cache.get(agent_id)
    if cached is not None:
        return cached

    try:
        from .auth import get_worker_auth_headers

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{nexus_url}/api/v1/agents/{agent_id}",
                headers=get_worker_auth_headers(org_id=org_id),
            )
            if resp.status_code == 200:
                data = resp.json()
                skills = data.get("effective_skills", [])
                _skill_cache[agent_id] = skills
                # Cache role alongside skills for learning hooks
                role = data.get("role", "coder")
                _role_cache[agent_id] = role
                return skills
    except Exception:
        logger.warning("Failed to fetch skills for agent %s", agent_id)
    return []


async def process_task(task_data: dict) -> None:
    """Build and invoke the appropriate LangGraph for a single task."""
    task_id = task_data.get("task_id", "unknown")
    graph_type = task_data.get("graph_type", "coding")

    # Bind task context for structured logging.
    request_id = task_data.get("request_id")
    bind_task_context(task_id=task_id, request_id=request_id)

    # -- Build graph (standard or custom) ----------------------------------------
    if graph_type == "custom":
        workflow_yaml = task_data.get("workflow_yaml")
        if not workflow_yaml:
            logger.error("Custom task %s missing workflow_yaml in payload", task_id)
            return

        logger.info("Processing task %s with custom workflow", task_id)

        from selva_workflows import WorkflowCompiler, WorkflowSerializer

        try:
            workflow_def = WorkflowSerializer.from_yaml(workflow_yaml)
            compiler = WorkflowCompiler()
            graph = compiler.compile(workflow_def)
        except Exception:
            logger.exception("Failed to compile custom workflow for task %s", task_id)
            return
        compiled = graph.compile(checkpointer=checkpointer)
    else:
        builder = GRAPH_BUILDERS.get(graph_type)
        if builder is None:
            logger.error("Unknown graph type '%s' for task %s", graph_type, task_id)
            return

        logger.info("Processing task %s with %s graph", task_id, graph_type)

        graph = builder()
        compiled = graph.compile(checkpointer=checkpointer)

    agent_id = (
        task_data.get("assigned_agent_ids", ["unknown"])[0]
        if task_data.get("assigned_agent_ids")
        else "unknown"
    )

    # Fetch agent skills and build skill-augmented system prompt
    settings = get_settings()
    skill_ids: list[str] = []
    agent_system_prompt = ""
    locale = task_data.get("payload", {}).get("locale", "en") if task_data.get("payload") else "en"
    # Resolve target tenant org_id early so all worker-to-API calls
    # below can present X-Selva-Tenant-Org. The audience resolution
    # below uses the same value.
    payload_for_audience = task_data.get("payload", {}) or {}
    task_org_id = task_data.get("org_id") or payload_for_audience.get("org_id") or ""
    try:
        skill_ids = await _fetch_agent_skills(
            settings.nexus_api_url, agent_id, org_id=task_org_id or None
        )
        if skill_ids:
            from selva_skills import get_skill_registry

            registry = get_skill_registry()
            agent_system_prompt = registry.build_system_prompt(skill_ids, locale=locale)
            logger.info(
                "Built skill prompt for agent %s with skills: %s (locale=%s)",
                agent_id,
                skill_ids,
                locale,
            )
    except Exception:
        logger.warning("Failed to build skill prompt for agent %s", agent_id, exc_info=True)

    # Merge locale into workflow_variables so graph nodes can read it.
    workflow_variables = task_data.get("payload", {}).get("variables", {}) or {}
    if locale != "en" and "locale" not in workflow_variables:
        workflow_variables["locale"] = locale

    # Resolve swarm audience from the (already-derived) task_org_id.
    # Platform org (per PLATFORM_ORG_ID env) gets Audience.PLATFORM and
    # can see all tools + platform skills; every other tenant gets
    # Audience.TENANT and only sees the filtered registry. We cast the
    # selva_permissions enum to the selva_tools enum so
    # ``enforce_audience()`` in the tool layer matches by identity.
    task_audience = ToolAudience(resolve_audience(task_org_id).value)

    initial_state: dict = {
        "messages": [],
        "task_id": task_id,
        "agent_id": agent_id,
        "status": "running",
        "result": None,
        "requires_approval": False,
        "approval_request_id": None,
        "agent_system_prompt": agent_system_prompt,
        "agent_skill_ids": skill_ids,
        "workflow_variables": workflow_variables,
        "locale": locale,
        "description": task_data.get("description", ""),
        "current_node_id": "",
        # Thread org_id + audience uniformly so every graph can reason
        # about which swarm this is running for.
        "org_id": task_org_id,
        "audience": task_audience.value,
    }

    # Add graph-specific state
    if graph_type == "coding":
        initial_state["code_changes"] = []
        initial_state["iteration"] = 0
    elif graph_type == "research":
        initial_state["query"] = task_data.get("description", "")
        initial_state["sources"] = []
    elif graph_type == "crm":
        payload = task_data.get("payload", {})
        initial_state["recipient"] = payload.get("contact_email") or payload.get(
            "recipient", "unknown@example.com"
        )
        initial_state["crm_action"] = payload.get("crm_action", "email")
        # Pass contact context from dispatch payload
        initial_state["contact_email"] = payload.get("contact_email", "")
        initial_state["contact_name"] = payload.get("contact_name", "")
        initial_state["product_interest"] = payload.get("product_interest", "")
        initial_state["lead_score"] = payload.get("lead_score")
        # T3.2 attribution — thread the lead_id through to the graph so
        # the send node can stamp it onto PostHog + UTM metadata.
        initial_state["lead_id"] = task_data.get("lead_id") or payload.get("lead_id", "")
        initial_state["utm_source"] = payload.get("utm_source", "selva")
        initial_state["utm_campaign"] = payload.get("utm_campaign", "hot_lead_auto")
        # Pass playbook data for conditional approval bypass
        playbook = task_data.get("playbook") or payload.get("playbook")
        if playbook:
            initial_state["playbook"] = playbook
    elif graph_type == "deployment":
        payload = task_data.get("payload", {})
        initial_state["service"] = payload.get("service", "")
        initial_state["environment"] = payload.get("environment", "staging")
        initial_state["image_tag"] = payload.get("image_tag", "latest")
        initial_state["overlay_path"] = payload.get("overlay_path", "")
        initial_state["repo_path"] = payload.get("repo_path") or settings.repo_base_path
        initial_state["gitops_app"] = payload.get("gitops_app", "")
        initial_state["smoke_checks"] = payload.get("smoke_checks", [])
        initial_state["current_pointer"] = payload.get("current_pointer", {})
        initial_state["rollback_pointer"] = payload.get("rollback_pointer", {})
    elif graph_type == "puppeteer":
        payload = task_data.get("payload", {})
        initial_state["subtasks"] = []
        initial_state["subtask_results"] = []
        initial_state["aggregated_result"] = None
        initial_state["max_parallel"] = payload.get("max_parallel", 3)
        initial_state["selected_agents"] = []
    elif graph_type == "meeting":
        payload = task_data.get("payload", {})
        initial_state["transcript"] = ""
        initial_state["summary"] = ""
        initial_state["action_items"] = []
        initial_state["recording_url"] = payload.get("recording_url", "")
    elif graph_type == "accounting":
        payload = task_data.get("payload", {})
        initial_state["org_id"] = payload.get("org_id", "")
        initial_state["period"] = payload.get("period", "")
        initial_state["rfc"] = payload.get("rfc", "")
        initial_state["regime"] = payload.get("regime", "pf")
        initial_state["transactions"] = []
        initial_state["bank_statements"] = []
        initial_state["pos_transactions"] = []
        initial_state["payment_summary"] = None
        initial_state["reconciliation"] = None
        initial_state["tax_computation"] = None
        initial_state["declaration_data"] = None
    elif graph_type == "billing":
        payload = task_data.get("payload", {})
        initial_state["emisor_rfc"] = payload.get("emisor_rfc", "")
        initial_state["receptor_rfc"] = payload.get("receptor_rfc", "")
        initial_state["conceptos"] = payload.get("conceptos", [])
        initial_state["cfdi_xml"] = None
        initial_state["cfdi_uuid"] = None
        initial_state["stamp_result"] = None
        initial_state["customer_phone"] = payload.get("customer_phone")
        initial_state["customer_email"] = payload.get("customer_email")
    elif graph_type == "intelligence":
        payload = task_data.get("payload", {})
        initial_state["org_id"] = payload.get("org_id", "")
        initial_state["dof_results"] = []
        initial_state["exchange_rate"] = None
        initial_state["economic_indicators"] = None
        initial_state["briefing_text"] = None
    elif graph_type == "operations":
        payload = task_data.get("payload", {})
        initial_state["org_id"] = payload.get("org_id", "")
        initial_state["sku"] = payload.get("sku")
        initial_state["pedimento_number"] = payload.get("pedimento_number")
        initial_state["tracking_numbers"] = payload.get("tracking_numbers", [])
        initial_state["inventory_status"] = None
    elif graph_type == "sales":
        payload = task_data.get("payload", {})
        initial_state["lead_id"] = payload.get("lead_id", "")
        initial_state["lead_data"] = None
        initial_state["cotizacion"] = None
        initial_state["pedido"] = None
        initial_state["billing_task_id"] = None
        initial_state["customer_phone"] = payload.get("customer_phone")
        initial_state["customer_email"] = payload.get("customer_email")

    handler = InterruptHandler(
        nexus_api_url=settings.nexus_api_url,
        redis_url=settings.redis_url,
        default_timeout=settings.approval_timeout,
        org_id=task_org_id or None,
    )

    # Set repo_path in initial state for coding graphs.
    if graph_type == "coding":
        repo_path = task_data.get("payload", {}).get("repo_path") or settings.repo_base_path
        # Expand ~ and ensure the directory exists and is writable.
        resolved_repo = Path(repo_path).expanduser().resolve()
        try:
            resolved_repo.mkdir(parents=True, exist_ok=True)
            # Quick writability check.
            _probe = resolved_repo / ".autoswarm-probe"
            _probe.touch()
            _probe.unlink()
        except OSError as exc:
            error_msg = f"Repo path {resolved_repo} is not writable: {exc}"
            logger.error(error_msg)
            await _update_task_status(
                settings.nexus_api_url,
                task_id,
                "failed",
                {"error": error_msg},
                error_message=error_msg,
                org_id=task_org_id or None,
            )
            await _publish_agent_status(agent_id, "error", current_node_id="")
            return
        initial_state["repo_path"] = str(resolved_repo)

    # Track timing for learning hooks
    _task_start = time.monotonic()
    agent_role = _role_cache.get(agent_id, "coder")
    description = task_data.get("description", "")

    # Notify Colyseus that this agent is now working.
    await _publish_agent_status(agent_id, "working")
    await _update_task_status(
        settings.nexus_api_url,
        task_id,
        "running",
        started_at=datetime.now(UTC).isoformat(),
        org_id=task_org_id or None,
    )
    await _emit_event(
        settings.nexus_api_url,
        event_type="task.started",
        event_category="task",
        task_id=task_id,
        agent_id=agent_id,
        graph_type=graph_type,
        request_id=request_id,
        org_id=task_org_id or "default",
    )

    try:
        # Apply per-graph-type timeout
        timeout = get_task_timeout(graph_type)

        # Bind the swarm's audience so any tool that calls
        # enforce_audience() sees the current task's audience. The
        # context is reset at the end of the ``with`` block so workers
        # that process multiple tasks concurrently don't leak audience
        # across tasks.
        with with_audience(task_audience):
            if graph_type == "custom":
                # Stream node progress for custom workflows
                result = await asyncio.wait_for(
                    _run_custom_with_streaming(compiled, initial_state, task_id, agent_id, handler),
                    timeout=timeout,
                )
            else:
                result = await asyncio.wait_for(
                    run_graph_with_interrupts(compiled, initial_state, task_id, agent_id, handler),
                    timeout=timeout,
                )
        graph_status = _state_str(result, "status", "completed")
        if graph_status in ("completed", "pushed"):
            api_status = "completed"
        elif graph_status in ("blocked", "error", "denied", "timeout"):
            api_status = "failed"
        else:
            api_status = "failed"
        api_result = _state_dict(result, "result")
        if graph_type == "deployment":
            api_result = {
                **api_result,
                "deploy_status": _state_str(result, "deploy_status"),
                "argo_sync_status": _state_str(result, "argo_sync_status"),
                "argo_health_status": _state_str(result, "argo_health_status"),
                "smoke_status": _state_str(result, "smoke_status"),
                "rollback_evidence_artifact": _state_dict(result, "rollback_evidence_artifact"),
                "deployment_evidence": _state_dict(result, "deployment_evidence"),
            }
        await _update_task_status(
            settings.nexus_api_url,
            task_id,
            api_status,
            api_result,
            org_id=task_org_id or None,
        )
        await _emit_event(
            settings.nexus_api_url,
            event_type="task.completed" if api_status == "completed" else "task.failed",
            event_category="task",
            task_id=task_id,
            agent_id=agent_id,
            graph_type=graph_type,
            request_id=request_id,
            org_id=task_org_id or "default",
        )
        # -- Learning hooks (fire-and-forget) ------------------------------------
        _duration = time.monotonic() - _task_start
        with contextlib.suppress(Exception):
            from .learning import (
                record_experience,
                update_agent_performance,
                update_bandit_reward,
            )

            await record_experience(
                agent_id,
                agent_role,
                description,
                graph_type,
                _state_dict(result, "result"),
                graph_status,
                duration_seconds=_duration,
            )
            await update_agent_performance(
                settings.nexus_api_url,
                agent_id,
                graph_status,
                duration_seconds=_duration,
                org_id=task_org_id or None,
            )
            await update_bandit_reward(agent_id, 1.0 if api_status == "completed" else 0.2)

        logger.info("Task %s completed with status: %s", task_id, _state_str(result, "status"))
        await _publish_agent_status(agent_id, "idle", current_node_id="")
    except TimeoutError:
        logger.error("Task %s timed out after %ds", task_id, timeout)
        await _update_task_status(
            settings.nexus_api_url,
            task_id,
            "failed",
            {"error": f"Timed out after {timeout}s"},
            error_message=f"Timed out after {timeout}s",
            org_id=task_org_id or None,
        )
        await _emit_event(
            settings.nexus_api_url,
            event_type="task.timeout",
            event_category="task",
            task_id=task_id,
            agent_id=agent_id,
            graph_type=graph_type,
            error_message=f"Timed out after {timeout}s",
            request_id=request_id,
            org_id=task_org_id or "default",
        )
        # -- Learning hooks (fire-and-forget) --------------------------------
        with contextlib.suppress(Exception):
            from .learning import (
                generate_reflexion,
                record_experience,
                update_agent_performance,
                update_bandit_reward,
            )

            _duration = time.monotonic() - _task_start
            await record_experience(
                agent_id,
                agent_role,
                description,
                graph_type,
                None,
                "failed",
                duration_seconds=_duration,
                error_message=f"Timed out after {timeout}s",
            )
            await generate_reflexion(
                agent_id,
                agent_role,
                description,
                graph_type,
                error_message=f"Timed out after {timeout}s",
            )
            await update_agent_performance(
                settings.nexus_api_url,
                agent_id,
                "failed",
                duration_seconds=_duration,
                org_id=task_org_id or None,
            )
            await update_bandit_reward(agent_id, 0.0)

        await _publish_agent_status(agent_id, "error", current_node_id="")
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        await _update_task_status(
            settings.nexus_api_url,
            task_id,
            "failed",
            {"error": str(exc)},
            error_message=str(exc),
            org_id=task_org_id or None,
        )
        await _emit_event(
            settings.nexus_api_url,
            event_type="task.failed",
            event_category="task",
            task_id=task_id,
            agent_id=agent_id,
            graph_type=graph_type,
            error_message=str(exc)[:500],
            request_id=request_id,
            org_id=task_org_id or "default",
        )
        # -- Learning hooks (fire-and-forget) --------------------------------
        with contextlib.suppress(Exception):
            from .learning import (
                generate_reflexion,
                record_experience,
                update_agent_performance,
                update_bandit_reward,
            )

            _duration = time.monotonic() - _task_start
            await record_experience(
                agent_id,
                agent_role,
                description,
                graph_type,
                None,
                "failed",
                duration_seconds=_duration,
                error_message=str(exc)[:500],
            )
            await generate_reflexion(
                agent_id,
                agent_role,
                description,
                graph_type,
                error_message=str(exc)[:500],
            )
            await update_agent_performance(
                settings.nexus_api_url,
                agent_id,
                "failed",
                duration_seconds=_duration,
                org_id=task_org_id or None,
            )
            await update_bandit_reward(agent_id, 0.0)

        await _publish_agent_status(agent_id, "error", current_node_id="")
    finally:
        await handler.close()
        clear_context()


async def _run_custom_with_streaming(
    compiled,  # noqa: ANN001
    initial_state: dict[str, object],
    task_id: str,
    agent_id: str,
    handler: InterruptHandler,
) -> dict[str, object]:
    """Run a custom workflow graph with per-node status streaming.

    Uses ``compiled.astream()`` to emit node progress events to Colyseus
    via Redis pub/sub, enabling real-time execution visualization.
    """
    config: dict[str, dict[str, str]] = {"configurable": {"thread_id": task_id}}
    result: dict[str, object] = {}

    async for event in compiled.astream(initial_state, config, stream_mode="updates"):
        if isinstance(event, dict):
            for node_id, node_output in event.items():
                logger.info("Task %s: node '%s' executed", task_id, node_id)
                await _publish_agent_status(agent_id, "working", current_node_id=node_id)
                if isinstance(node_output, dict):
                    result.update(node_output)

    # Check for interrupts after streaming completes
    snapshot = compiled.get_state(config)
    while snapshot.next:
        interrupt_value = None
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_value = snapshot.tasks[0].interrupts[0].value

        action_category = "api_call"
        payload: dict[str, object] = {"task_id": task_id}
        reasoning = f"Agent {agent_id} requires approval during task {task_id}."
        if isinstance(interrupt_value, dict):
            action_category = interrupt_value.get("action_category", action_category)
            payload.update(interrupt_value)
            reasoning = interrupt_value.get("reasoning", reasoning)

        request_id = await handler.create_approval_request(
            agent_id=agent_id,
            action_category=action_category,
            payload=payload,
            reasoning=reasoning,
        )
        await _publish_agent_status(agent_id, "waiting_approval")
        approval = await handler.wait_for_approval(request_id)
        resume_value = {
            "approved": approval.result == "approved",
            "feedback": approval.feedback,
        }
        await _publish_agent_status(agent_id, "working")

        async for event in compiled.astream(
            Command(resume=resume_value), config, stream_mode="updates"
        ):
            if isinstance(event, dict):
                for node_id, node_output in event.items():
                    logger.info("Task %s: node '%s' executed (post-resume)", task_id, node_id)
                    await _publish_agent_status(agent_id, "working", current_node_id=node_id)
                    if isinstance(node_output, dict):
                        result.update(node_output)

        snapshot = compiled.get_state(config)

    return result


async def _cleanup_stale_worktrees(repo_base: str, stale_hours: int = 24) -> int:
    """Remove worktree directories older than *stale_hours*.

    Scans ``<repo_base>/*/_worktrees/*/`` for stale directories.
    Returns the number of worktrees removed.
    """
    import time

    base = Path(repo_base).expanduser().resolve()
    if not base.exists():
        return 0

    cutoff = time.time() - (stale_hours * _SECONDS_PER_HOUR)
    removed = 0

    for worktree_root in base.glob("*/_worktrees"):
        try:
            if not worktree_root.is_dir():
                continue
            entries = list(worktree_root.iterdir())
        except OSError:
            logger.warning("Could not enumerate worktree root: %s", worktree_root)
            continue
        for wt_dir in entries:
            try:
                if not wt_dir.is_dir():
                    continue
                mtime = wt_dir.stat().st_mtime
                if mtime < cutoff:
                    shutil.rmtree(wt_dir, ignore_errors=True)
                    removed += 1
                    logger.info("Removed stale worktree: %s", wt_dir)
            except OSError:
                logger.warning("Could not stat worktree: %s", wt_dir)

    if removed > 0:
        logger.info("Cleaned up %d stale worktree(s) from %s", removed, base)
    return removed


async def _periodic_cleanup(repo_base: str, stale_hours: int) -> None:
    """Run _cleanup_stale_worktrees periodically."""
    while not _shutdown.is_set():
        await asyncio.sleep(_SECONDS_PER_HOUR)  # Every hour
        if _shutdown.is_set():
            break
        try:
            await _cleanup_stale_worktrees(repo_base, stale_hours)
        except Exception:
            logger.exception("Failed during periodic worktree cleanup")


# Active concurrent tasks tracked for graceful shutdown.
_active_tasks: set[asyncio.Task[None]] = set()
_task_semaphore: asyncio.Semaphore | None = None


async def _process_with_semaphore(
    consumer: TaskStreamConsumer,
    msg_id: str,
    task_data: dict,
) -> None:
    """Process a single task under the concurrency semaphore."""
    assert _task_semaphore is not None
    task_id = task_data.get("task_id", "unknown")
    async with _task_semaphore:
        try:
            await process_task(task_data)
            await consumer.ack(msg_id)
        except Exception:
            logger.exception("Task %s failed (msg_id=%s)", task_id, msg_id)
            retries = await consumer.retry_count(msg_id)
            if retries >= MAX_RETRIES:
                error_msg = f"Max retries ({MAX_RETRIES}) exceeded"
                await consumer.move_to_dlq(msg_id, task_data, error_msg)


def _coerce_json_field(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


async def _claim_pending_db_tasks(settings, limit: int) -> list[dict[str, object]]:
    """Claim DB-pending tasks that missed Redis publication.

    Nexus marks tasks as ``pending`` when the database write succeeded but
    Redis Stream publication failed. This worker-side reclaim loop treats
    ``swarm_tasks`` as a minimal durable outbox until a dedicated outbox table
    exists.
    """
    if not settings.database_url:
        return []

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    worker_id = f"db-reclaim:{id(asyncio.current_task())}"
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    WITH claimed AS (
                        SELECT id
                        FROM swarm_tasks
                        WHERE status = 'pending'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM swarm_task_outbox o
                              WHERE o.task_id = swarm_tasks.id
                                AND o.status IN ('pending', 'retryable')
                          )
                        ORDER BY created_at
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE swarm_tasks AS t
                    SET status = 'queued',
                        retry_count = retry_count + 1,
                        worker_id = :worker_id
                    FROM claimed
                    WHERE t.id = claimed.id
                    RETURNING
                        t.id::text AS id,
                        t.description AS description,
                        t.graph_type AS graph_type,
                        t.assigned_agent_ids AS assigned_agent_ids,
                        t.payload AS payload,
                        t.org_id AS org_id,
                        t.workflow_id::text AS workflow_id,
                        (
                            SELECT yaml_content
                            FROM workflows
                            WHERE workflows.id = t.workflow_id
                        ) AS workflow_yaml
                    """
                ),
                {"limit": limit, "worker_id": worker_id},
            )
            rows = result.mappings().all()
    except Exception:
        logger.warning("Failed to reclaim DB-pending swarm tasks", exc_info=True)
        return []
    finally:
        await engine.dispose()

    reclaimed: list[dict[str, object]] = []
    for row in rows:
        payload = _coerce_json_field(row.get("payload"), {})
        assigned_agent_ids = _coerce_json_field(row.get("assigned_agent_ids"), [])
        if not isinstance(payload, dict):
            payload = {}
        if not isinstance(assigned_agent_ids, list):
            assigned_agent_ids = []
        envelope = payload.get("_selva_envelope") if isinstance(payload, dict) else None
        if not isinstance(envelope, dict):
            envelope = {}

        org_id = str(row.get("org_id") or envelope.get("org_id") or "")
        graph_type = str(row.get("graph_type") or envelope.get("graph_type") or "sequential")
        task_data: dict[str, object] = {
            "schema": "selva.task-envelope/v1",
            "task_id": str(row["id"]),
            "org_id": org_id,
            "audience": envelope.get("audience") or resolve_audience(org_id).value,
            "graph_type": graph_type,
            "idempotency_key": envelope.get("idempotency_key") or str(row["id"]),
            "source": envelope.get("source") or "db-reclaim",
            "desired_state_hash": envelope.get("desired_state_hash"),
            "description": str(row.get("description") or ""),
            "assigned_agent_ids": assigned_agent_ids,
            "required_skills": (
                payload.get("required_skills", [])
                if isinstance(payload, dict)
                else []
            ),
            "payload": payload,
            "request_id": envelope.get("request_id"),
        }
        workflow_yaml = row.get("workflow_yaml")
        if workflow_yaml:
            task_data["workflow_yaml"] = str(workflow_yaml)
        reclaimed.append(task_data)

    if reclaimed:
        logger.warning("Reclaimed %d DB-pending swarm task(s)", len(reclaimed))
    return reclaimed


async def _publish_retryable_outbox(settings, limit: int) -> int:
    """Publish pending/retryable swarm task outbox rows to Redis Streams."""
    if not settings.database_url:
        return 0

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    pool = get_redis_pool()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    published = 0
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        id::text AS id,
                        task_id::text AS task_id,
                        stream_name,
                        payload,
                        retry_count
                    FROM swarm_task_outbox
                    WHERE status IN ('pending', 'retryable')
                      AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
                    ORDER BY created_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"limit": limit},
            )
            rows = result.mappings().all()

            for row in rows:
                outbox_id = str(row["id"])
                task_id = str(row["task_id"])
                stream_name = str(row["stream_name"] or "autoswarm:task-stream")
                payload = _coerce_json_field(row.get("payload"), {})
                if not isinstance(payload, dict):
                    payload = {}

                try:
                    msg_id = await pool.execute_with_retry(
                        "xadd",
                        stream_name,
                        {"data": json.dumps(payload)},
                    )
                    stream_message_id = str(msg_id)
                    await conn.execute(
                        text(
                            """
                            UPDATE swarm_task_outbox
                            SET status = 'sent',
                                stream_message_id = :stream_message_id,
                                last_error = NULL,
                                sent_at = NOW(),
                                updated_at = NOW()
                            WHERE id = CAST(:outbox_id AS uuid)
                            """
                        ),
                        {
                            "outbox_id": outbox_id,
                            "stream_message_id": stream_message_id,
                        },
                    )
                    await conn.execute(
                        text(
                            """
                            UPDATE swarm_tasks
                            SET status = 'queued',
                                stream_message_id = :stream_message_id
                            WHERE id = CAST(:task_id AS uuid)
                              AND status = 'pending'
                            """
                        ),
                        {
                            "task_id": task_id,
                            "stream_message_id": stream_message_id,
                        },
                    )
                    published += 1
                except Exception as exc:
                    retry_count = int(row.get("retry_count") or 0) + 1
                    backoff_seconds = min(
                        _OUTBOX_MAX_BACKOFF_SECONDS,
                        2 ** min(retry_count, 6),
                    )
                    next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)
                    await conn.execute(
                        text(
                            """
                            UPDATE swarm_task_outbox
                            SET status = 'retryable',
                                retry_count = retry_count + 1,
                                last_error = :last_error,
                                next_attempt_at = :next_attempt_at,
                                updated_at = NOW()
                            WHERE id = CAST(:outbox_id AS uuid)
                            """
                        ),
                        {
                            "outbox_id": outbox_id,
                            "last_error": str(exc)[:_OUTBOX_ERROR_MAX_LENGTH],
                            "next_attempt_at": next_attempt_at,
                        },
                    )
                    logger.warning(
                        "Failed to publish swarm_task_outbox row %s for task %s",
                        outbox_id,
                        task_id,
                        exc_info=True,
                    )
    except Exception:
        logger.warning("Failed to drain swarm task outbox", exc_info=True)
        return published
    finally:
        await engine.dispose()

    if published:
        logger.info("Published %d swarm task outbox row(s)", published)
    return published


async def _process_db_task_with_semaphore(task_data: dict[str, object]) -> None:
    assert _task_semaphore is not None
    task_id = task_data.get("task_id", "unknown")
    async with _task_semaphore:
        try:
            await process_task(task_data)
        except Exception:
            logger.exception("DB-reclaimed task %s failed before status update", task_id)


async def _periodic_pending_db_reclaim(settings) -> None:
    interval = max(settings.redis_block_timeout_ms / 1000, 5.0)
    while not _shutdown.is_set():
        await asyncio.sleep(interval)
        if _shutdown.is_set() or _task_semaphore is None:
            continue
        tasks = await _claim_pending_db_tasks(settings, settings.max_concurrent_tasks)
        for task_data in tasks:
            if _shutdown.is_set():
                break
            task = asyncio.create_task(_process_db_task_with_semaphore(task_data))
            _active_tasks.add(task)
            task.add_done_callback(_active_tasks.discard)


async def _periodic_outbox_publish(settings) -> None:
    interval = max(settings.redis_block_timeout_ms / 1000, 5.0)
    while not _shutdown.is_set():
        await asyncio.sleep(interval)
        if _shutdown.is_set():
            continue
        await _publish_retryable_outbox(settings, settings.max_concurrent_tasks)


async def main() -> None:
    """Entry point: connect to Redis and consume the task stream."""
    global _task_semaphore  # noqa: PLW0603

    settings = get_settings()
    logger.info("Worker configuration validated")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Initialize Redis pool
    pool = get_redis_pool(url=settings.redis_url)

    if not await pool.ping():
        logger.error("Cannot connect to Redis at %s", settings.redis_url)
        sys.exit(1)

    logger.info("Connected to Redis at %s", settings.redis_url)

    # Cleanup stale worktrees from previous runs.
    await _cleanup_stale_worktrees(settings.repo_base_path, settings.worktree_stale_hours)

    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(
        _periodic_cleanup(settings.repo_base_path, settings.worktree_stale_hours),
    )
    _active_tasks.add(cleanup_task)
    cleanup_task.add_done_callback(_active_tasks.discard)

    # Start scheduled-action drain loop.
    # Drains ScheduledAction.SOCIAL_POST rows once per minute. See
    # selva_workers/jobs/social_post_executor.py for the full design
    # (Celery vs APScheduler decision, HITL respect, rate-limit
    # rescheduling, dead-letter, and the budget-gate TODO).
    from .jobs.social_post_executor import (
        periodic_loop as _scheduled_action_periodic_loop,
    )

    scheduled_action_task = asyncio.create_task(
        _scheduled_action_periodic_loop(_shutdown),
    )
    _active_tasks.add(scheduled_action_task)
    scheduled_action_task.add_done_callback(_active_tasks.discard)

    # Start dragon-egg warmup drain loop.
    # Sibling job to the scheduled-action drain — drains
    # social_account_warmup_actions every 60s and dispatches the
    # platform tool for ``planned`` actions whose ``scheduled_for <=
    # NOW()``. See selva_workers/jobs/dragon_egg_warmup.py for the
    # full design (HITL respect, tool routing, content_brief
    # contract, budget-gate TODO).
    from .jobs.dragon_egg_warmup import (
        periodic_loop as _dragon_egg_warmup_loop,
    )

    dragon_egg_task = asyncio.create_task(_dragon_egg_warmup_loop(_shutdown))
    _active_tasks.add(dragon_egg_task)
    dragon_egg_task.add_done_callback(_active_tasks.discard)

    # Log available inference providers at startup.
    from .inference import validate_providers

    validate_providers()

    # Set up Redis Streams consumer
    consumer = TaskStreamConsumer()
    await consumer.ensure_group()

    # Claim any stalled messages from crashed workers
    stalled = await consumer.claim_stalled()
    for msg_id, task_data in stalled:
        logger.info("Re-processing stalled task %s (msg_id=%s)", task_data.get("task_id"), msg_id)
        try:
            await process_task(task_data)
            await consumer.ack(msg_id)
        except Exception:
            logger.exception("Failed to process stalled task %s", msg_id)

    logger.info(
        "Worker listening on stream '%s' (max_concurrent=%d)",
        "autoswarm:task-stream",
        settings.max_concurrent_tasks,
    )

    # Initialize concurrency semaphore
    _task_semaphore = asyncio.Semaphore(settings.max_concurrent_tasks)

    pending_db_reclaim_task = asyncio.create_task(_periodic_pending_db_reclaim(settings))
    _active_tasks.add(pending_db_reclaim_task)
    pending_db_reclaim_task.add_done_callback(_active_tasks.discard)

    outbox_publish_task = asyncio.create_task(_periodic_outbox_publish(settings))
    _active_tasks.add(outbox_publish_task)
    outbox_publish_task.add_done_callback(_active_tasks.discard)

    # Exponential backoff state for connection errors
    backoff_delay = 1.0
    max_backoff = 60.0

    try:
        while not _shutdown.is_set():
            if _shutdown.is_set():
                break

            try:
                messages = await consumer.read(
                    count=settings.max_concurrent_tasks,
                    block=settings.redis_block_timeout_ms,
                )
                if not messages:
                    continue

                # Reset backoff on successful read
                backoff_delay = 1.0

                for msg_id, task_data in messages:
                    if _shutdown.is_set():
                        break

                    task = asyncio.create_task(_process_with_semaphore(consumer, msg_id, task_data))
                    _active_tasks.add(task)
                    task.add_done_callback(_active_tasks.discard)

            except ConnectionError:
                logger.warning("Redis connection lost, retrying in %.1fs...", backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, max_backoff)
    finally:
        # Drain active tasks on shutdown.
        if _active_tasks:
            logger.info("Draining %d active task(s)...", len(_active_tasks))
            await asyncio.gather(*_active_tasks, return_exceptions=True)
        # Release Postgres checkpoint pool BEFORE Redis pool. Order
        # matters: in-flight tasks above may still be writing
        # checkpoints; closing the checkpoint pool first while tasks
        # could still be running would race. Drain finished above
        # guarantees no task is mid-checkpoint when this runs.
        close_checkpointer()
        await pool.close()
        logger.info("Worker shut down")


if __name__ == "__main__":
    asyncio.run(main())
