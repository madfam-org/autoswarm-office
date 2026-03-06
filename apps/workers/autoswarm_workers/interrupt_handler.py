"""Bridge between LangGraph interrupt() events and the Nexus API approval system."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel

from .graphs.base import BaseGraphState

logger = logging.getLogger(__name__)


class ApprovalResponse(BaseModel):
    """Structured response from the Nexus API approval endpoint."""

    request_id: str
    result: str  # "approved" | "denied"
    feedback: str | None = None
    responded_at: str | None = None


@dataclass
class InterruptHandler:
    """Bridges LangGraph graph interrupts to the Nexus API approval workflow.

    When a graph node calls ``interrupt()``, the worker process invokes
    this handler to:

    1. POST an approval request to the Nexus API.
    2. Poll the API until the Tactician approves or denies the request.
    3. Return the decision so the graph can resume.
    """

    nexus_api_url: str
    redis_url: str = "redis://localhost:6379"
    client: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=30.0))

    async def create_approval_request(
        self,
        agent_id: str,
        action_category: str,
        payload: dict[str, Any],
        reasoning: str,
        urgency: str = "medium",
        diff: str | None = None,
    ) -> str:
        """Create a new approval request in the Nexus API.

        Args:
            agent_id: UUID of the agent requesting approval.
            action_category: The action type (e.g. ``git_push``, ``email_send``).
            payload: Context-specific data for the reviewer.
            reasoning: Human-readable explanation of why approval is needed.
            urgency: One of ``low``, ``medium``, ``high``, ``critical``.
            diff: Optional diff or preview content.

        Returns:
            The UUID of the created approval request.

        Raises:
            httpx.HTTPStatusError: If the API returns an error status.
        """
        url = f"{self.nexus_api_url.rstrip('/')}/api/v1/approvals"

        body = {
            "agent_id": agent_id,
            "action_category": action_category,
            "action_type": action_category,
            "payload": payload,
            "reasoning": reasoning,
            "urgency": urgency,
            "diff": diff,
        }

        response = await self.client.post(url, json=body)
        response.raise_for_status()

        data = response.json()
        request_id: str = data["id"]
        logger.info(
            "Created approval request %s for agent %s (category: %s)",
            request_id,
            agent_id,
            action_category,
        )
        return request_id

    async def _wait_via_redis(self, request_id: str, timeout: int) -> ApprovalResponse:
        """Subscribe to the Redis pub/sub channel and wait for the decision.

        This is the preferred path -- no polling, instant notification.
        """
        channel_name = f"autoswarm:approval:{request_id}"
        redis_client = aioredis.from_url(self.redis_url, decode_responses=True)

        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel_name)

            async def _get_message() -> ApprovalResponse:
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg is not None and msg["type"] == "message":
                        data = json.loads(msg["data"])
                        return ApprovalResponse(
                            request_id=data["request_id"],
                            result=data["result"],
                            feedback=data.get("feedback"),
                        )

            result = await asyncio.wait_for(_get_message(), timeout=timeout)
            logger.info("Approval request %s resolved via Redis pub/sub: %s", request_id, result.result)
            return result
        finally:
            await pubsub.unsubscribe(channel_name)
            await redis_client.aclose()

    async def _wait_via_polling(
        self, request_id: str, timeout: int, poll_interval: float
    ) -> ApprovalResponse:
        """Fallback: poll the Nexus API until the approval request is resolved."""
        url = f"{self.nexus_api_url.rstrip('/')}/api/v1/approvals/{request_id}"
        elapsed = 0.0

        while elapsed < timeout:
            response = await self.client.get(url)
            response.raise_for_status()

            data = response.json()
            status = data.get("status", "pending")

            if status in ("approved", "denied"):
                approval = ApprovalResponse(
                    request_id=data["id"],
                    result=status,
                    feedback=data.get("feedback"),
                    responded_at=data.get("responded_at"),
                )
                logger.info(
                    "Approval request %s resolved via polling: %s", request_id, approval.result
                )
                return approval

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Approval request {request_id} was not resolved within {timeout} seconds"
        )

    async def wait_for_approval(
        self,
        request_id: str,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> ApprovalResponse:
        """Wait for an approval decision, preferring Redis pub/sub with polling fallback.

        Args:
            request_id: UUID of the approval request to monitor.
            timeout: Maximum seconds to wait before timing out.
            poll_interval: Seconds between poll attempts (used only in fallback).

        Returns:
            The resolved ``ApprovalResponse``.

        Raises:
            TimeoutError: If no decision is made within *timeout* seconds.
            httpx.HTTPStatusError: If the API returns an error status during polling.
        """
        try:
            return await self._wait_via_redis(request_id, timeout)
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                raise
            logger.warning(
                "Redis subscribe failed for %s (%s), falling back to polling",
                request_id,
                exc,
            )
            return await self._wait_via_polling(request_id, timeout, poll_interval)

    async def handle_interrupt(self, state: BaseGraphState) -> BaseGraphState:
        """Full interrupt handling flow: create request, wait, update state.

        This method is called when a graph node has set
        ``requires_approval=True`` in the state.  It creates the
        approval request, waits for the Tactician's decision, and
        updates the state accordingly.

        Args:
            state: The current graph state with approval context.

        Returns:
            Updated state with approval result reflected in ``status``
            and ``approval_request_id``.
        """
        agent_id = state.get("agent_id", "unknown")
        task_id = state.get("task_id", "unknown")

        # Extract action details from the last message.
        messages = state.get("messages", [])
        action_category = "api_call"
        payload: dict[str, Any] = {"task_id": task_id}

        if messages:
            last = messages[-1]
            kwargs = getattr(last, "additional_kwargs", {})
            action_category = kwargs.get("action_category", "api_call")
            payload.update(kwargs)

        reasoning = f"Agent {agent_id} requires approval for '{action_category}' during task {task_id}."

        try:
            request_id = await self.create_approval_request(
                agent_id=agent_id,
                action_category=action_category,
                payload=payload,
                reasoning=reasoning,
            )

            approval = await self.wait_for_approval(request_id)

            if approval.result == "approved":
                return {
                    **state,
                    "status": "approved",
                    "requires_approval": False,
                    "approval_request_id": request_id,
                }

            return {
                **state,
                "status": "denied",
                "requires_approval": False,
                "approval_request_id": request_id,
                "result": {"denied_feedback": approval.feedback},
            }

        except TimeoutError:
            logger.error("Approval timed out for agent %s, task %s", agent_id, task_id)
            return {
                **state,
                "status": "timeout",
                "requires_approval": False,
            }

        except httpx.HTTPError as exc:
            logger.error("Nexus API error during approval flow: %s", exc)
            return {
                **state,
                "status": "error",
                "requires_approval": False,
                "result": {"error": str(exc)},
            }

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
