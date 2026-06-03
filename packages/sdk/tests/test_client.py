"""Tests for the Selva async and sync clients."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from selva_sdk import Selva, SelvaSync
from selva_sdk.exceptions import (
    AuthenticationError,
    NotFoundError,
    SelvaError,
    TaskTimeoutError,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

TASK_QUEUED: dict[str, Any] = {
    "id": "aaaa-bbbb-cccc",
    "description": "Fix login bug",
    "graph_type": "coding",
    "assigned_agent_ids": [],
    "payload": {},
    "status": "queued",
    "created_at": "2026-03-14T00:00:00",
    "completed_at": None,
}

TASK_COMPLETED: dict[str, Any] = {**TASK_QUEUED, "status": "completed"}

AGENTS: list[dict[str, Any]] = [
    {
        "id": "agent-1",
        "name": "Alice",
        "role": "coder",
        "status": "idle",
        "level": 3,
        "department_id": None,
        "skill_ids": None,
        "effective_skills": ["python", "git"],
    },
    {
        "id": "agent-2",
        "name": "Bob",
        "role": "reviewer",
        "status": "working",
        "level": 5,
        "department_id": "dept-1",
        "skill_ids": ["code_review"],
        "effective_skills": ["code_review"],
    },
]


def _make_transport(
    handler: httpx.MockTransport | None = None,
) -> httpx.MockTransport:
    """Return the transport if provided (type helper)."""
    assert handler is not None
    return handler


# ---------------------------------------------------------------------------
# Async client tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_success() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/swarms/dispatch"
        body = json.loads(request.content)
        assert body["description"] == "Fix login bug"
        assert body["graph_type"] == "coding"
        return httpx.Response(201, json=TASK_QUEUED)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        task = await client.dispatch("Fix login bug")
        assert task.id == "aaaa-bbbb-cccc"
        assert task.status == "queued"


@pytest.mark.asyncio
async def test_dispatch_auth_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    async with Selva(base_url="http://test", token="bad") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        with pytest.raises(AuthenticationError) as exc_info:
            await client.dispatch("Test")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_budget_exceeded() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"detail": "Compute token budget exceeded for today"})

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        with pytest.raises(SelvaError) as exc_info:
            await client.dispatch("Test")
        assert exc_info.value.status_code == 402
        assert "budget exceeded" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_list_agents_success() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agents/"
        return httpx.Response(200, json=AGENTS)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        agents = await client.list_agents()
        assert len(agents) == 2
        assert agents[0].name == "Alice"
        assert agents[1].role == "reviewer"


@pytest.mark.asyncio
async def test_get_task_success() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/swarms/tasks/" in request.url.path
        return httpx.Response(200, json=TASK_QUEUED)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        task = await client.get_task("aaaa-bbbb-cccc")
        assert task.description == "Fix login bug"


@pytest.mark.asyncio
async def test_get_task_not_found() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Task not found"})

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        with pytest.raises(NotFoundError) as exc_info:
            await client.get_task("nonexistent")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_wait_for_task_success() -> None:
    """Simulates two polls: first returns queued, second returns completed."""
    call_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=TASK_QUEUED)
        return httpx.Response(200, json=TASK_COMPLETED)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        task = await client.wait_for_task("aaaa-bbbb-cccc", poll_interval=0.01, timeout=5.0)
        assert task.status == "completed"
        assert call_count == 2


@pytest.mark.asyncio
async def test_wait_for_task_timeout() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TASK_QUEUED)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        with pytest.raises(TaskTimeoutError):
            await client.wait_for_task("aaaa-bbbb-cccc", poll_interval=0.01, timeout=0.03)


@pytest.mark.asyncio
async def test_context_manager() -> None:
    """Verify async context manager opens and closes cleanly."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=AGENTS)

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        agents = await client.list_agents()
        assert len(agents) == 2
    # After exiting context, client should be closed (no assertion needed;
    # if close fails, httpx would raise).


@pytest.mark.asyncio
async def test_generic_api_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    async with Selva(base_url="http://test", token="tok") as client:
        client._client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        )
        with pytest.raises(SelvaError) as exc_info:
            await client.list_agents()
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Sync client tests
# ---------------------------------------------------------------------------


def test_sync_dispatch() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=TASK_QUEUED)

    client = SelvaSync(base_url="http://test", token="tok")
    client._async._client = httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(handle),
    )
    task = client.dispatch("Fix login bug")
    assert task.id == "aaaa-bbbb-cccc"
    client.close()


def test_sync_list_agents() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=AGENTS)

    client = SelvaSync(base_url="http://test", token="tok")
    client._async._client = httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(handle),
    )
    agents = client.list_agents()
    assert len(agents) == 2
    assert agents[0].name == "Alice"
    client.close()
