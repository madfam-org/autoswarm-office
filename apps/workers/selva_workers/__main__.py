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
from datetime import UTC, datetime
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

from .checkpointer import create_checkpointer
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
        graph_status = result.get("status", "completed")
        if graph_status in ("completed", "pushed"):
            api_status = "completed"
        elif graph_status in ("blocked", "error", "denied", "timeout"):
            api_status = "failed"
        else:
            api_status = "completed"
        await _update_task_status(
            settings.nexus_api_url,
            task_id,
            api_status,
            result.get("result"),
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
                result.get("result"),
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

        logger.info("Task %s completed with status: %s", task_id, result.get("status"))
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
        if not worktree_root.is_dir():
            continue
        for wt_dir in worktree_root.iterdir():
            if not wt_dir.is_dir():
                continue
            try:
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
_active_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
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
        await pool.close()
        logger.info("Worker shut down")


if __name__ == "__main__":
    asyncio.run(main())
