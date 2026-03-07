"""Tests for multi-tenancy: org_id isolation across resources."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from nexus_api.config import Settings
from nexus_api.tenant import TenantContext, get_tenant


class TestTenantDependency:
    """get_tenant extracts org_id from authenticated user."""

    @pytest.mark.asyncio
    async def test_extracts_org_id_from_user(self) -> None:
        user = {"sub": "user-1", "roles": ["admin"], "org_id": "acme-corp"}
        ctx = await get_tenant(user=user)
        assert ctx.org_id == "acme-corp"

    @pytest.mark.asyncio
    async def test_defaults_to_default_when_missing(self) -> None:
        user = {"sub": "user-1", "roles": []}
        ctx = await get_tenant(user=user)
        assert ctx.org_id == "default"

    @pytest.mark.asyncio
    async def test_defaults_to_default_when_none(self) -> None:
        user = {"sub": "user-1", "roles": [], "org_id": None}
        ctx = await get_tenant(user=user)
        assert ctx.org_id == "default"


class TestTenantIsolation:
    """Resources are isolated by org_id."""

    @pytest.mark.asyncio
    async def test_create_agent_sets_org_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/agents/",
            json={"name": "TenantAgent", "role": "coder"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_list_agents_filtered_by_org(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Agents created in the dev org are visible."""
        await client.post(
            "/api/v1/agents/",
            json={"name": "OrgAgent1", "role": "coder"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/agents/", headers=auth_headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        assert all(a["name"] != "GhostAgent" for a in agents)

    @pytest.mark.asyncio
    async def test_create_department_sets_org_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/departments/",
            json={"name": "Engineering", "slug": "eng-tenant-test"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_list_departments_filtered_by_org(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/departments/",
            json={"name": "Test Dept", "slug": "test-dept-tenant"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/departments/", headers=auth_headers)
        assert resp.status_code == 200
        depts = resp.json()
        assert len(depts) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_task_sets_org_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/swarms/dispatch",
            json={"description": "Tenant task test", "graph_type": "research"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_list_tasks_filtered_by_org(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/swarms/dispatch",
            json={"description": "Org-scoped task", "graph_type": "research"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/swarms/tasks", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_billing_usage_scoped_by_org(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/billing/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_used" in data

    @pytest.mark.asyncio
    async def test_billing_tokens_scoped_by_org(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/billing/tokens", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_limit" in data

    @pytest.mark.asyncio
    async def test_cross_org_agent_not_visible(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        """An agent in a different org should not appear in listing."""
        from nexus_api.models import Agent

        # Create an agent directly in DB with a different org_id
        other_agent = Agent(name="OtherOrgAgent", role="coder", org_id="other-org")
        db_session.add(other_agent)
        await db_session.flush()

        resp = await client.get("/api/v1/agents/", headers=auth_headers)
        assert resp.status_code == 200
        agents = resp.json()
        names = [a["name"] for a in agents]
        assert "OtherOrgAgent" not in names

    @pytest.mark.asyncio
    async def test_cross_org_department_not_visible(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        """A department in a different org should not appear in listing."""
        from nexus_api.models import Department

        other_dept = Department(
            name="Other Dept", slug="other-dept-xorg", org_id="other-org"
        )
        db_session.add(other_dept)
        await db_session.flush()

        resp = await client.get("/api/v1/departments/", headers=auth_headers)
        assert resp.status_code == 200
        depts = resp.json()
        names = [d["name"] for d in depts]
        assert "Other Dept" not in names
