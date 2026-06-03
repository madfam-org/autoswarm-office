"""A2A protocol server -- mount as a FastAPI sub-application.

Provides the three core A2A endpoints:

* ``GET /.well-known/agent.json`` -- agent discovery card
* ``POST /tasks/send`` -- one-shot task dispatch
* ``POST /tasks/sendSubscribe`` -- SSE streaming for long-running tasks
* ``GET /tasks/{task_id}`` -- poll task status
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schema import AgentCard, AgentSkill, TaskRequest, TaskResponse, TaskStatus

logger = logging.getLogger(__name__)

# Type aliases for the callback signatures
SkillsProvider = Callable[[], list[AgentSkill]]
TaskDispatcher = Callable[[TaskRequest], Awaitable[str]]
TaskStatusGetter = Callable[[str], Awaitable[TaskResponse]]


def create_a2a_router(
    agent_name: str = "Selva Office",
    base_url: str = "",
    get_skills: SkillsProvider | None = None,
    dispatch_task: TaskDispatcher | None = None,
    get_task_status: TaskStatusGetter | None = None,
) -> APIRouter:
    """Build a FastAPI router implementing the A2A protocol.

    Parameters
    ----------
    agent_name:
        Human-readable name surfaced in the AgentCard.
    base_url:
        Public URL where this agent is reachable.
    get_skills:
        Optional callable returning the agent's advertised skills.
    dispatch_task:
        Optional async callable that accepts a ``TaskRequest`` and returns
        a task ID string.  Required for ``tasks/send`` and ``tasks/sendSubscribe``.
    get_task_status:
        Optional async callable that accepts a task ID and returns a
        ``TaskResponse``.  Required for ``tasks/{task_id}``.
    """
    router = APIRouter(prefix="/a2a", tags=["A2A Protocol"])

    @router.get("/.well-known/agent.json", response_model=AgentCard)
    async def agent_card() -> AgentCard:
        """Return the agent discovery card."""
        skills = get_skills() if get_skills else []
        return AgentCard(name=agent_name, url=base_url, skills=skills)

    @router.post("/tasks/send", response_model=TaskResponse)
    async def send_task(req: TaskRequest) -> TaskResponse:
        """Accept a task from an external agent (one-shot)."""
        if not dispatch_task:
            raise HTTPException(status_code=501, detail="Task dispatch not configured")
        try:
            task_id = await dispatch_task(req)
        except Exception:
            logger.exception("A2A task dispatch failed")
            raise HTTPException(status_code=502, detail="Internal dispatch error") from None
        return TaskResponse(task_id=task_id, status=TaskStatus.PENDING)

    @router.get("/tasks/{task_id}", response_model=TaskResponse)
    async def get_task(task_id: str) -> TaskResponse:
        """Poll the status of an A2A task."""
        if not get_task_status:
            raise HTTPException(status_code=501, detail="Task status lookup not configured")
        try:
            return await get_task_status(task_id)
        except Exception:
            logger.exception("A2A task status lookup failed for %s", task_id)
            raise HTTPException(status_code=502, detail="Internal status lookup error") from None

    @router.post("/tasks/sendSubscribe")
    async def send_subscribe(req: TaskRequest) -> StreamingResponse:
        """Accept a task and stream status updates via SSE."""
        if not dispatch_task:
            raise HTTPException(status_code=501, detail="Task dispatch not configured")
        try:
            task_id = await dispatch_task(req)
        except Exception:
            logger.exception("A2A subscribe dispatch failed")
            raise HTTPException(status_code=502, detail="Internal dispatch error") from None

        async def event_stream() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'task_id': task_id, 'status': 'pending'})}\n\n"
            for _ in range(60):
                await asyncio.sleep(5)
                if get_task_status:
                    try:
                        resp = await get_task_status(task_id)
                        yield f"data: {resp.model_dump_json()}\n\n"
                        if resp.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                            return
                    except Exception:
                        logger.debug("SSE poll error for task %s", task_id, exc_info=True)
            # Timeout after 5 minutes of polling
            timeout_payload = json.dumps(
                {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "SSE poll timeout",
                }
            )
            yield f"data: {timeout_payload}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return router
