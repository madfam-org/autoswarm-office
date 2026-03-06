"""AutoSwarm worker process -- Redis BRPOP consumer for LangGraph execution."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

import redis.asyncio as aioredis

from .config import get_settings
from .graphs.coding import build_coding_graph
from .graphs.crm import build_crm_graph
from .graphs.research import build_research_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("autoswarm.worker")

QUEUE_KEY = "autoswarm:tasks"
GRAPH_BUILDERS = {
    "coding": build_coding_graph,
    "research": build_research_graph,
    "crm": build_crm_graph,
}

_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger.info("Received %s, shutting down...", sig.name)
    _shutdown.set()


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
    compiled = graph.compile()

    initial_state: dict = {
        "messages": [],
        "task_id": task_id,
        "agent_id": (
            task_data.get("assigned_agent_ids", ["unknown"])[0]
            if task_data.get("assigned_agent_ids")
            else "unknown"
        ),
        "status": "running",
        "result": None,
        "requires_approval": False,
        "approval_request_id": None,
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

    try:
        result = await asyncio.to_thread(compiled.invoke, initial_state)
        logger.info("Task %s completed with status: %s", task_id, result.get("status"))
    except Exception:
        logger.exception("Task %s failed", task_id)


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
