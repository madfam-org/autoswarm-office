"""Bridge between LangGraph interrupt() events and the Nexus API approval system."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel

from selva_redis_pool import get_redis_pool

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
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    default_timeout: int = 300
    auth_headers: dict[str, str] = field(default_factory=dict)
    # Target tenant org_id for nexus-api auth resolution. Threaded through
    # the X-Selva-Tenant-Org header so approval requests post under the
    # correct tenant scope. When None, calls fall back to platform scope
    # (incorrect for tenant-owned approval rows — callers should set this).
    org_id: str | None = None
    client: httpx.AsyncClient = field(init=False)

    def __post_init__(self) -> None:
        if not self.auth_headers:
            from .auth import get_worker_auth_headers

            self.auth_headers = get_worker_auth_headers(org_id=self.org_id)
        self.client = httpx.AsyncClient(timeout=30.0, headers=self.auth_headers)

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
        url = f"{self.nexus_api_url.rstrip('/')}/api/v1/approvals/"

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
        channel_name = f"selva:approval:{request_id}"
        pool = get_redis_pool(url=self.redis_url)
        redis_client = await pool.client()
        pubsub = redis_client.pubsub()

        try:
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
            logger.info(
                "Approval request %s resolved via Redis pub/sub: %s",
                request_id,
                result.result,
            )
            return result
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()

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

            jittered = poll_interval * (0.5 + random.random())
            await asyncio.sleep(jittered)
            elapsed += jittered

        raise TimeoutError(
            f"Approval request {request_id} was not resolved within {timeout} seconds"
        )

    async def wait_for_approval(
        self,
        request_id: str,
        timeout: int | None = None,
        poll_interval: float = 0.5,
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
        if timeout is None:
            timeout = self.default_timeout
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

        reasoning = (
            f"Agent {agent_id} requires approval for '{action_category}' during task {task_id}."
        )

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
