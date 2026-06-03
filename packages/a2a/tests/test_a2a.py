"""Tests for the Selva A2A protocol package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from selva_a2a.client import A2AClient
from selva_a2a.schema import (
    AgentCard,
    AgentSkill,
    TaskRequest,
    TaskResponse,
    TaskStatus,
)
from selva_a2a.server import create_a2a_router

# -- Schema tests -------------------------------------------------------------


class TestAgentCard:
    def test_defaults(self):
        card = AgentCard()
        assert card.name == "Selva Office"
        assert "tasks/send" in card.capabilities
        assert "tasks/get" in card.capabilities
        assert "tasks/sendSubscribe" in card.capabilities
        assert card.authentication == {"schemes": ["bearer"]}

    def test_custom_fields(self):
        card = AgentCard(
            name="TestAgent",
            url="https://test.example.com",
            skills=[AgentSkill(id="s1", name="Coding", description="Write code")],
        )
        assert card.name == "TestAgent"
        assert len(card.skills) == 1
        assert card.skills[0].id == "s1"


class TestTaskRequest:
    def test_defaults(self):
        req = TaskRequest(description="Fix the bug")
        assert req.graph_type == "coding"
        assert req.metadata == {}

    def test_custom_graph_type(self):
        req = TaskRequest(description="Analyze data", graph_type="research")
        assert req.graph_type == "research"


class TestTaskResponse:
    def test_completed_status(self):
        resp = TaskResponse(task_id="abc-123", status=TaskStatus.COMPLETED)
        assert resp.status == TaskStatus.COMPLETED
        assert resp.result is None
        assert resp.error is None

    def test_failed_with_error(self):
        resp = TaskResponse(
            task_id="abc-123",
            status=TaskStatus.FAILED,
            error="Out of memory",
        )
        assert resp.status == TaskStatus.FAILED
        assert resp.error == "Out of memory"

    def test_with_result(self):
        resp = TaskResponse(
            task_id="abc-123",
            status=TaskStatus.COMPLETED,
            result={"pr_url": "https://github.com/org/repo/pull/42"},
        )
        assert resp.result["pr_url"].endswith("/42")


class TestAgentSkill:
    def test_with_tags(self):
        skill = AgentSkill(
            id="coding",
            name="Coding",
            description="Write and review code",
            tags=["python", "typescript"],
        )
        assert len(skill.tags) == 2

    def test_empty_tags_default(self):
        skill = AgentSkill(id="review", name="Review", description="Code review")
        assert skill.tags == []


# -- Server tests -------------------------------------------------------------


def _build_test_app(
    dispatch_task: object = None,
    get_task_status: object = None,
    get_skills: object = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the A2A router mounted."""
    app = FastAPI()
    router = create_a2a_router(
        agent_name="TestAgent",
        base_url="http://localhost:4300",
        get_skills=get_skills,
        dispatch_task=dispatch_task,
        get_task_status=get_task_status,
    )
    app.include_router(router)
    return app


class TestAgentCardEndpoint:
    def test_returns_card(self):
        app = _build_test_app()
        client = TestClient(app)
        resp = client.get("/a2a/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TestAgent"
        assert data["url"] == "http://localhost:4300"

    def test_returns_skills(self):
        def skills() -> list[AgentSkill]:
            return [
                AgentSkill(id="coding", name="Coding", description="Write code"),
            ]

        app = _build_test_app(get_skills=skills)
        client = TestClient(app)
        resp = client.get("/a2a/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 1
        assert data["skills"][0]["id"] == "coding"


class TestSendTaskEndpoint:
    def test_dispatch_returns_pending(self):
        async def fake_dispatch(req: TaskRequest) -> str:
            return "task-001"

        app = _build_test_app(dispatch_task=fake_dispatch)
        client = TestClient(app)
        resp = client.post(
            "/a2a/tasks/send",
            json={"description": "Fix the login page"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["status"] == "pending"

    def test_dispatch_not_configured(self):
        app = _build_test_app()
        client = TestClient(app)
        resp = client.post(
            "/a2a/tasks/send",
            json={"description": "Fix the login page"},
        )
        assert resp.status_code == 501

    def test_dispatch_error_returns_502(self):
        async def bad_dispatch(req: TaskRequest) -> str:
            raise RuntimeError("boom")

        app = _build_test_app(dispatch_task=bad_dispatch)
        client = TestClient(app)
        resp = client.post(
            "/a2a/tasks/send",
            json={"description": "Fix the login page"},
        )
        assert resp.status_code == 502


class TestGetTaskEndpoint:
    def test_get_task_returns_status(self):
        async def fake_status(task_id: str) -> TaskResponse:
            return TaskResponse(task_id=task_id, status=TaskStatus.RUNNING)

        app = _build_test_app(get_task_status=fake_status)
        client = TestClient(app)
        resp = client.get("/a2a/tasks/task-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["status"] == "running"

    def test_get_task_not_configured(self):
        app = _build_test_app()
        client = TestClient(app)
        resp = client.get("/a2a/tasks/task-001")
        assert resp.status_code == 501


class TestSendSubscribeEndpoint:
    def test_subscribe_not_configured(self):
        app = _build_test_app()
        client = TestClient(app)
        resp = client.post(
            "/a2a/tasks/sendSubscribe",
            json={"description": "Long task"},
        )
        assert resp.status_code == 501


# -- Client tests -------------------------------------------------------------


class TestA2AClient:
    @pytest.mark.asyncio
    async def test_discover(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "name": "RemoteAgent",
            "capabilities": ["tasks/send"],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)
            client = A2AClient()
            card = await client.discover("http://remote.example.com/a2a")

        assert card.name == "RemoteAgent"

    @pytest.mark.asyncio
    async def test_send_task(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "task_id": "remote-task-1",
            "status": "pending",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            client = A2AClient()
            resp = await client.send_task(
                "http://remote.example.com/a2a",
                TaskRequest(description="Do something"),
                token="secret-token",
            )

        assert resp.task_id == "remote-task-1"
        assert resp.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_task(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "task_id": "remote-task-1",
            "status": "completed",
            "result": {"output": "done"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)
            client = A2AClient()
            resp = await client.get_task(
                "http://remote.example.com/a2a",
                "remote-task-1",
            )

        assert resp.status == TaskStatus.COMPLETED
        assert resp.result == {"output": "done"}

    def test_auth_headers_with_token(self):
        headers = A2AClient._auth_headers("my-token")
        assert headers == {"Authorization": "Bearer my-token"}

    def test_auth_headers_without_token(self):
        headers = A2AClient._auth_headers(None)
        assert headers == {}
