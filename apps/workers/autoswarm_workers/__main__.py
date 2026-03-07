"""AutoSwarm worker process -- Redis BRPOP consumer for LangGraph execution."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

import httpx
import redis.asyncio as aioredis
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .config import get_settings
from .graphs.coding import build_coding_graph
from .graphs.crm import build_crm_graph
from .graphs.research import build_research_graph
from .interrupt_handler import InterruptHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("autoswarm.worker")

QUEUE_KEY = "autoswarm:tasks"
AGENT_STATUS_CHANNEL = "autoswarm:agent-status"
GRAPH_BUILDERS = {
    "coding": build_coding_graph,
    "research": build_research_graph,
    "crm": build_crm_graph,
}

checkpointer = MemorySaver()

_shutdown = asyncio.Event()


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
        settings = get_settings()
        await _publish_agent_status(settings.redis_url, agent_id, "waiting_approval")

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

        result = await asyncio.to_thread(
            compiled.invoke, Command(resume=resume_value), config
        )

    return result


async def _publish_agent_status(redis_url: str, agent_id: str, new_status: str) -> None:
    """Publish an agent status change to Redis for Colyseus consumption."""
    if agent_id == "unknown":
        return
    try:
        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.publish(
            AGENT_STATUS_CHANNEL,
            json.dumps({"agent_id": agent_id, "status": new_status}),
        )
        await client.aclose()
    except Exception:
        logger.warning("Failed to publish agent status for %s", agent_id)


async def _fetch_agent_skills(nexus_url: str, agent_id: str) -> list[str]:
    """GET /api/v1/agents/{agent_id} and return effective_skills."""
    if agent_id == "unknown":
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{nexus_url}/api/v1/agents/{agent_id}")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("effective_skills", [])
    except Exception:
        logger.warning("Failed to fetch skills for agent %s", agent_id)
    return []


async def process_task(task_data: dict) -> None:
    """Build and invoke the appropriate LangGraph for a single task."""
    task_id = task_data.get("task_id", "unknown")
    graph_type = task_data.get("graph_type", "coding")

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
    try:
        skill_ids = await _fetch_agent_skills(settings.nexus_api_url, agent_id)
        if skill_ids:
            from autoswarm_skills import get_skill_registry

            registry = get_skill_registry()
            agent_system_prompt = registry.build_system_prompt(skill_ids)
            logger.info("Built skill prompt for agent %s with skills: %s", agent_id, skill_ids)
    except Exception:
        logger.warning("Failed to build skill prompt for agent %s", agent_id, exc_info=True)

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
        initial_state["recipient"] = payload.get("recipient", "unknown@example.com")
        initial_state["crm_action"] = payload.get("crm_action", "email")

    settings = get_settings()
    handler = InterruptHandler(
        nexus_api_url=settings.nexus_api_url,
        redis_url=settings.redis_url,
    )

    # Notify Colyseus that this agent is now working.
    await _publish_agent_status(settings.redis_url, agent_id, "working")

    try:
        result = await run_graph_with_interrupts(
            compiled, initial_state, task_id, agent_id, handler
        )
        logger.info("Task %s completed with status: %s", task_id, result.get("status"))
        await _publish_agent_status(settings.redis_url, agent_id, "idle")
    except Exception:
        logger.exception("Task %s failed", task_id)
        await _publish_agent_status(settings.redis_url, agent_id, "error")
    finally:
        await handler.close()


async def main() -> None:
    """Entry point: connect to Redis and consume the task queue."""
    settings = get_settings()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        await redis_client.ping()
        logger.info("Connected to Redis at %s", settings.redis_url)
    except Exception:
        logger.error("Cannot connect to Redis at %s", settings.redis_url)
        sys.exit(1)

    logger.info("Worker listening on queue '%s'", QUEUE_KEY)

    try:
        while not _shutdown.is_set():
            try:
                result = await redis_client.brpop(QUEUE_KEY, timeout=5)
                if result is None:
                    continue

                _, raw = result
                task_data = json.loads(raw)
                await process_task(task_data)
            except json.JSONDecodeError as exc:
                logger.error("Invalid JSON in task queue: %s", exc)
            except aioredis.ConnectionError:
                logger.warning("Redis connection lost, reconnecting in 5s...")
                await asyncio.sleep(5)
    finally:
        await redis_client.aclose()
        logger.info("Worker shut down")


if __name__ == "__main__":
    asyncio.run(main())
