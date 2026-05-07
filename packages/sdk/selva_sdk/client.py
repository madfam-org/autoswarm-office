"""Async and sync AutoSwarm API clients."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import httpx

from .exceptions import AuthenticationError, AutoSwarmError, NotFoundError, TaskTimeoutError
from .models import (
    AgentResponse,
    DispatchRequest,
    KanbanMetricsResponse,
    KanbanTaskImportResponse,
    OverdueNotificationResponse,
    TaskBoardResponse,
    TaskClaimResponse,
    TaskCommentResponse,
    TaskHistoryResponse,
    TaskResponse,
)

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class AutoSwarm:
    """Async AutoSwarm API client."""

    def __init__(
        self,
        base_url: str = "http://localhost:4300",
        token: str = "dev-token",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> AutoSwarm:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _handle_response(self, resp: httpx.Response) -> None:
        """Raise typed exceptions for non-2xx responses."""
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                f"Authentication failed: {resp.status_code}", resp.status_code
            )
        if resp.status_code == 404:
            raise NotFoundError("Resource not found", 404)
        if resp.status_code >= 400:
            detail = resp.text
            with contextlib.suppress(Exception):
                detail = resp.json().get("detail", detail)
            raise AutoSwarmError(f"API error {resp.status_code}: {detail}", resp.status_code)

    async def dispatch(
        self,
        description: str,
        graph_type: str = "coding",
        title: str | None = None,
        assigned_agent_ids: list[str] | None = None,
        required_skills: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        priority: str = "medium",
        labels: list[str] | None = None,
        due_date: str | None = None,
    ) -> TaskResponse:
        """Dispatch a new swarm task and return the created task."""
        req = DispatchRequest(
            title=title,
            description=description,
            graph_type=graph_type,
            assigned_agent_ids=assigned_agent_ids or [],
            required_skills=required_skills or [],
            payload=payload or {},
            workflow_id=workflow_id,
            priority=priority,
            labels=labels or [],
            due_date=due_date,
        )
        resp = await self._client.post(
            "/api/v1/swarms/dispatch",
            json=req.model_dump(exclude_none=True),
        )
        self._handle_response(resp)
        return TaskResponse.model_validate(resp.json())

    async def get_kanban_board(self) -> TaskBoardResponse:
        """Return the kanban board grouped by status."""
        resp = await self._client.get("/api/v1/swarms/tasks/board")
        self._handle_response(resp)
        return TaskBoardResponse.model_validate(resp.json())

    async def update_task_kanban(
        self,
        task_id: str,
        *,
        kanban_status: str | None = None,
        title: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        parent_task_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> TaskResponse:
        """Update first-class kanban metadata for a task."""
        body = {
            "kanban_status": kanban_status,
            "title": title,
            "priority": priority,
            "labels": labels,
            "due_date": due_date,
            "parent_task_id": parent_task_id,
            "depends_on": depends_on,
        }
        resp = await self._client.patch(
            f"/api/v1/swarms/tasks/{task_id}/kanban",
            json={k: v for k, v in body.items() if v is not None},
        )
        self._handle_response(resp)
        return TaskResponse.model_validate(resp.json())

    async def add_task_comment(self, task_id: str, body: str) -> TaskCommentResponse:
        """Add a durable comment to a task."""
        resp = await self._client.post(
            f"/api/v1/swarms/tasks/{task_id}/comments",
            json={"body": body},
        )
        self._handle_response(resp)
        return TaskCommentResponse.model_validate(resp.json())

    async def get_task_history(self, task_id: str) -> list[TaskHistoryResponse]:
        """Return append-only task history."""
        resp = await self._client.get(f"/api/v1/swarms/tasks/{task_id}/history")
        self._handle_response(resp)
        return [TaskHistoryResponse.model_validate(item) for item in resp.json()]

    async def claim_task(
        self,
        agent_id: str | None = None,
        graph_type: str | None = None,
        labels: list[str] | None = None,
    ) -> TaskClaimResponse:
        """Claim the next available kanban task."""
        resp = await self._client.post(
            "/api/v1/swarms/tasks/claim",
            json={"agent_id": agent_id, "graph_type": graph_type, "labels": labels or []},
        )
        self._handle_response(resp)
        return TaskClaimResponse.model_validate(resp.json())

    async def notify_overdue_tasks(self) -> OverdueNotificationResponse:
        """Emit overdue lifecycle notifications for active kanban tasks."""
        resp = await self._client.post("/api/v1/swarms/tasks/notify-overdue")
        self._handle_response(resp)
        return OverdueNotificationResponse.model_validate(resp.json())

    async def export_kanban_tasks(
        self,
        format: str = "json",
        kanban_status: str | None = None,
    ) -> dict[str, Any] | str:
        """Export kanban tasks as JSON data or CSV text."""
        params = {"format": format}
        if kanban_status:
            params["kanban_status"] = kanban_status
        resp = await self._client.get("/api/v1/swarms/tasks/export", params=params)
        self._handle_response(resp)
        if format == "csv":
            return resp.text
        return resp.json()

    async def import_kanban_tasks(
        self,
        data: dict[str, Any] | list[dict[str, Any]] | str,
        format: str = "json",
    ) -> KanbanTaskImportResponse:
        """Import kanban tasks from JSON-compatible data or CSV text."""
        if format == "csv":
            resp = await self._client.post(
                "/api/v1/swarms/tasks/import",
                params={"format": "csv"},
                content=str(data),
                headers={"Content-Type": "text/csv"},
            )
        else:
            resp = await self._client.post(
                "/api/v1/swarms/tasks/import",
                params={"format": "json"},
                json=data,
            )
        self._handle_response(resp)
        return KanbanTaskImportResponse.model_validate(resp.json())

    async def get_kanban_metrics(self) -> KanbanMetricsResponse:
        """Return kanban-specific metrics."""
        resp = await self._client.get("/api/v1/swarms/tasks/kanban-metrics")
        self._handle_response(resp)
        return KanbanMetricsResponse.model_validate(resp.json())

    async def list_agents(self) -> list[AgentResponse]:
        """List all agents in the organization."""
        resp = await self._client.get("/api/v1/agents/")
        self._handle_response(resp)
        return [AgentResponse.model_validate(a) for a in resp.json()]

    async def get_task(self, task_id: str) -> TaskResponse:
        """Retrieve a single task by ID."""
        resp = await self._client.get(f"/api/v1/swarms/tasks/{task_id}")
        self._handle_response(resp)
        return TaskResponse.model_validate(resp.json())

    async def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> TaskResponse:
        """Poll a task until it reaches a terminal status or the timeout elapses."""
        start = asyncio.get_event_loop().time()
        while True:
            task = await self.get_task(task_id)
            if task.status in _TERMINAL_STATUSES:
                return task
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                raise TaskTimeoutError(f"Task {task_id} did not complete within {timeout}s")
            await asyncio.sleep(poll_interval)


class AutoSwarmSync:
    """Synchronous wrapper around the async AutoSwarm client."""

    def __init__(
        self,
        base_url: str = "http://localhost:4300",
        token: str = "dev-token",
    ) -> None:
        self._async = AutoSwarm(base_url=base_url, token=token)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        asyncio.run(self._async.close())

    def __enter__(self) -> AutoSwarmSync:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def dispatch(
        self,
        description: str,
        graph_type: str = "coding",
        **kwargs: Any,
    ) -> TaskResponse:
        """Dispatch a new swarm task (blocking)."""
        return asyncio.run(self._async.dispatch(description, graph_type, **kwargs))

    def list_agents(self) -> list[AgentResponse]:
        """List all agents (blocking)."""
        return asyncio.run(self._async.list_agents())

    def get_task(self, task_id: str) -> TaskResponse:
        """Retrieve a single task by ID (blocking)."""
        return asyncio.run(self._async.get_task(task_id))

    def get_kanban_board(self) -> TaskBoardResponse:
        """Return the kanban board grouped by status (blocking)."""
        return asyncio.run(self._async.get_kanban_board())

    def update_task_kanban(self, task_id: str, **kwargs: Any) -> TaskResponse:
        """Update kanban metadata (blocking)."""
        return asyncio.run(self._async.update_task_kanban(task_id, **kwargs))

    def add_task_comment(self, task_id: str, body: str) -> TaskCommentResponse:
        """Add a durable task comment (blocking)."""
        return asyncio.run(self._async.add_task_comment(task_id, body))

    def get_task_history(self, task_id: str) -> list[TaskHistoryResponse]:
        """Return append-only task history (blocking)."""
        return asyncio.run(self._async.get_task_history(task_id))

    def claim_task(
        self,
        agent_id: str | None = None,
        graph_type: str | None = None,
        labels: list[str] | None = None,
    ) -> TaskClaimResponse:
        """Claim the next available kanban task (blocking)."""
        return asyncio.run(self._async.claim_task(agent_id, graph_type, labels))

    def notify_overdue_tasks(self) -> OverdueNotificationResponse:
        """Emit overdue lifecycle notifications (blocking)."""
        return asyncio.run(self._async.notify_overdue_tasks())

    def export_kanban_tasks(
        self,
        format: str = "json",
        kanban_status: str | None = None,
    ) -> dict[str, Any] | str:
        """Export kanban tasks as JSON data or CSV text (blocking)."""
        return asyncio.run(self._async.export_kanban_tasks(format, kanban_status))

    def import_kanban_tasks(
        self,
        data: dict[str, Any] | list[dict[str, Any]] | str,
        format: str = "json",
    ) -> KanbanTaskImportResponse:
        """Import kanban tasks from JSON-compatible data or CSV text (blocking)."""
        return asyncio.run(self._async.import_kanban_tasks(data, format))

    def get_kanban_metrics(self) -> KanbanMetricsResponse:
        """Return kanban-specific metrics (blocking)."""
        return asyncio.run(self._async.get_kanban_metrics())

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> TaskResponse:
        """Poll a task until terminal status (blocking)."""
        start = time.monotonic()
        while True:
            task = asyncio.run(self._async.get_task(task_id))
            if task.status in _TERMINAL_STATUSES:
                return task
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                raise TaskTimeoutError(f"Task {task_id} did not complete within {timeout}s")
            time.sleep(poll_interval)
