"""Event emitter -- fire-and-forget POST to nexus-api + Redis PUBLISH."""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import time
import uuid
from typing import Any

from selva_redis_pool import get_redis_pool

from .http_retry import fire_and_forget_request

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "autoswarm:events"

# -- Module-internal constants -------------------------------------------------
# Per-event emit timeout (seconds) used by the synchronous fallback path
# (`_fire`) when an instrumented LangGraph node emits its node.entered /
# node.exited / node.error events from a sync context. The fire-and-forget
# nature means we'd rather drop the event than block the node — keep
# this value tight.
_EVENT_EMIT_TIMEOUT_S: int = 3


async def emit_event(
    nexus_url: str,
    *,
    event_type: str,
    event_category: str,
    task_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    graph_type: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    token_count: int | None = None,
    error_message: str | None = None,
    request_id: str | None = None,
    org_id: str = "default",
) -> None:
    """Emit an observability event.

    Fire-and-forget: failures are logged but never raised, matching the
    same resilience pattern used by ``task_status.py``.
    """
    body: dict[str, Any] = {
        "event_type": event_type,
        "event_category": event_category,
    }
    if task_id and task_id != "unknown":
        body["task_id"] = task_id
    if agent_id and agent_id != "unknown":
        body["agent_id"] = agent_id
    if node_id is not None:
        body["node_id"] = node_id
    if graph_type is not None:
        body["graph_type"] = graph_type
    if payload is not None:
        body["payload"] = payload
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if provider is not None:
        body["provider"] = provider
    if model is not None:
        body["model"] = model
    if token_count is not None:
        body["token_count"] = token_count
    if error_message is not None:
        body["error_message"] = error_message
    if request_id is not None:
        body["request_id"] = request_id
    if org_id != "default":
        body["org_id"] = org_id

    # POST to nexus-api (with retry and circuit breaker).
    # Pass org_id through the X-Selva-Tenant-Org header so nexus-api
    # auth.py resolves the worker token to the correct tenant scope
    # (instead of the hardcoded platform default).
    from .auth import get_worker_auth_headers

    auth_org_id = org_id if org_id and org_id != "default" else None
    await fire_and_forget_request(
        "POST",
        f"{nexus_url}/api/v1/events/",
        json=body,
        headers=get_worker_auth_headers(org_id=auth_org_id),
        timeout=2.0,
    )

    # Also PUBLISH to Redis for real-time WS relay
    try:
        pool = get_redis_pool()
        # Include a generated id and created_at for the WS consumers
        broadcast = {
            **body,
            "id": str(uuid.uuid4()),
            "created_at": time.time(),
        }
        await pool.execute_with_retry("publish", EVENTS_CHANNEL, json.dumps(broadcast))
    except Exception:
        logger.warning("Failed to PUBLISH event %s to Redis", event_type)


def instrumented_node(fn):  # type: ignore[no-untyped-def]
    """Decorator that emits node.entered / node.exited / node.error events.

    Wraps a synchronous LangGraph node function. Measures duration via
    ``time.monotonic()``. Extracts ``task_id``, ``agent_id``, and
    ``org_id`` from the state dict passed as the first argument.
    """

    @functools.wraps(fn)
    def wrapper(state, *args, **kwargs):  # type: ignore[no-untyped-def]
        import asyncio
        import concurrent.futures

        task_id = state.get("task_id", "unknown") if isinstance(state, dict) else "unknown"
        agent_id = state.get("agent_id", "unknown") if isinstance(state, dict) else "unknown"
        graph_type = state.get("graph_type") if isinstance(state, dict) else None
        # Pull org_id off the state so events post under the correct
        # tenant scope (every graph node already has it threaded in via
        # __main__.process_task's initial_state).
        state_org_id = state.get("org_id", "") if isinstance(state, dict) else ""
        org_id_arg = state_org_id if state_org_id else "default"
        node_name = fn.__name__

        # Resolve nexus_url lazily
        from .config import get_settings

        nexus_url = get_settings().nexus_api_url

        def _fire(coro):  # type: ignore[no-untyped-def]
            """Run an async coroutine fire-and-forget from sync context."""
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                with contextlib.suppress(Exception):
                    asyncio.run(coro)
                return
            with concurrent.futures.ThreadPoolExecutor(  # noqa: SIM117
                max_workers=1,
            ) as pool:
                with contextlib.suppress(Exception):
                    pool.submit(asyncio.run, coro).result(timeout=_EVENT_EMIT_TIMEOUT_S)

        _fire(
            emit_event(
                nexus_url,
                event_type="node.entered",
                event_category="node",
                task_id=task_id,
                agent_id=agent_id,
                node_id=node_name,
                graph_type=graph_type,
                org_id=org_id_arg,
            )
        )

        start = time.monotonic()
        try:
            result = fn(state, *args, **kwargs)
            elapsed = int((time.monotonic() - start) * 1000)

            _fire(
                emit_event(
                    nexus_url,
                    event_type="node.exited",
                    event_category="node",
                    task_id=task_id,
                    agent_id=agent_id,
                    node_id=node_name,
                    graph_type=graph_type,
                    duration_ms=elapsed,
                    org_id=org_id_arg,
                )
            )

            return result
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)

            _fire(
                emit_event(
                    nexus_url,
                    event_type="node.error",
                    event_category="node",
                    task_id=task_id,
                    agent_id=agent_id,
                    node_id=node_name,
                    graph_type=graph_type,
                    duration_ms=elapsed,
                    error_message=str(exc)[:500],
                    org_id=org_id_arg,
                )
            )

            raise

    return wrapper
