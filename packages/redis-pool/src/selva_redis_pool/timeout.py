"""Task timeout protection for worker graph execution."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

# Per-graph-type timeouts in seconds (env-configurable)
DEFAULT_TIMEOUTS: dict[str, int] = {
    "accounting": 600,
    "billing": 300,
    "campaign": 300,
    "coding": 600,
    "research": 300,
    "crm": 120,
    "deployment": 300,
    "intelligence": 300,
    "operations": 300,
    "puppeteer": 600,
    "meeting": 300,
    "sales": 300,
}


def get_task_timeout(graph_type: str) -> int:
    """Get the timeout for a graph type, checking env vars first."""
    env_key = f"TASK_TIMEOUT_{graph_type.upper()}"
    env_val = os.environ.get(env_key)
    if env_val:
        return int(env_val)
    return DEFAULT_TIMEOUTS.get(graph_type, 300)


async def run_with_timeout(
    coro: Callable[..., Awaitable[Any]],
    graph_type: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run an async callable with a graph-type-specific timeout."""
    timeout = get_task_timeout(graph_type)
    return await asyncio.wait_for(coro(*args, **kwargs), timeout=timeout)
