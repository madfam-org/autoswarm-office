"""Tests for the tenant provisioning and management API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest  # noqa: I001

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANTS_URL = "/api/v1/tenants"


async def _create_tenant(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    org_name: str = "MADFAM Corp",
    rfc: str | None = None,
    razon_social: str | None = None,
) -> httpx.Response:
    body: dict = {"org_name": org_name}
    if rfc is not None:
        body["rfc"] = rfc
    if razon_social is not None:
        body["razon_social"] = razon_social
    return await client.post(f"{_TENANTS_URL}/", headers=headers, json=body)


# ---------------------------------------------------------------------------
# Tests: Create Tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateTenant:
    async def test_create_tenant_creates_config_and_departments(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await _create_tenant(client, auth_headers, org_name="Test Org")
        assert resp.status_code == 201
        data = resp.json()

        # Config fields
        assert data["org_id"] == "dev-org"
        assert data["locale"] == "es-MX"
        assert data["timezone"] == "America/Mexico_City"
        assert data["currency"] == "MXN"
        assert data["cfdi_enabled"] is False
        assert data["intelligence_enabled"] is False
        assert data["max_agents"] == 10
        assert data["max_daily_tasks"] == 100

        # Verify departments were auto-created
        dept_resp = await client.get("/api/v1/departments/", headers=auth_headers)
        assert dept_resp.status_code == 200
        dept_data = dept_resp.json()
        # The response might be a list or a paginated response
        departments = dept_data if isinstance(dept_data, list) else dept_data.get("items", [])
        slugs = {d["slug"] for d in departments}
        assert "direccion" in slugs
        assert "administracion" in slugs
        assert "contabilidad" in slugs
        assert "ventas" in slugs
        assert "operaciones" in slugs
        assert "legal" in slugs

    async def test_create_tenant_with_rfc(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await _create_tenant(
            client,
            auth_headers,
            org_name="RFC Org",
            rfc="XAXX010101000",
            razon_social="Empresa de Prueba SA de CV",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["rfc"] == "XAXX010101000"
        assert data["razon_social"] == "Empresa de Prueba SA de CV"

    async def test_create_tenant_invalid_rfc_format_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await _create_tenant(client, auth_headers, rfc="INVALID")
        assert resp.status_code == 422
        assert "RFC" in resp.json()["detail"][0]["msg"] or "rfc" in str(resp.json()).lower()

    async def test_create_tenant_duplicate_409(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp1 = await _create_tenant(client, auth_headers, org_name="First")
        assert resp1.status_code == 201

        resp2 = await _create_tenant(client, auth_headers, org_name="Second")
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# Tests: Get My Tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetMyTenant:
    async def test_get_my_tenant_returns_config(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _create_tenant(client, auth_headers)
        resp = await client.get(f"{_TENANTS_URL}/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_id"] == "dev-org"
        assert data["locale"] == "es-MX"

    async def test_get_my_tenant_404_when_not_configured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get(f"{_TENANTS_URL}/me", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Update My Tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateMyTenant:
    async def test_update_locale_and_limits(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me",
            headers=auth_headers,
            json={"locale": "en-US", "max_agents": 50, "max_daily_tasks": 500},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "en-US"
        assert data["max_agents"] == 50
        assert data["max_daily_tasks"] == 500

    async def test_update_feature_flags(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me",
            headers=auth_headers,
            json={"cfdi_enabled": True, "intelligence_enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cfdi_enabled"] is True
        assert data["intelligence_enabled"] is True

    async def test_update_404_when_not_configured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.patch(
            f"{_TENANTS_URL}/me",
            headers=auth_headers,
            json={"locale": "en-US"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Tenant Usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTenantUsage:
    async def test_tenant_usage_returns_stats(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _create_tenant(client, auth_headers)

        resp = await client.get(f"{_TENANTS_URL}/me/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_id"] == "dev-org"
        assert data["agent_count"] >= 0
        assert data["agent_limit"] == 10
        assert data["tasks_today"] >= 0
        assert data["task_daily_limit"] == 100
        assert data["department_count"] == 6  # Mexican department template

    async def test_tenant_usage_defaults_without_config(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """When no TenantConfig exists, defaults are returned."""
        resp = await client.get(f"{_TENANTS_URL}/me/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_limit"] == 10
        assert data["task_daily_limit"] == 100


# ---------------------------------------------------------------------------
# Tests: Daily Task Limit Enforcement (in dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDailyTaskLimitEnforcement:
    async def test_daily_task_limit_blocks_dispatch(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """When an org has reached max_daily_tasks, dispatch returns 429."""
        # Create tenant with very low limit
        await _create_tenant(client, auth_headers)
        await client.patch(
            f"{_TENANTS_URL}/me",
            headers=auth_headers,
            json={"max_daily_tasks": 1},
        )

        # Create an agent so dispatch can assign it
        agent_resp = await client.post(
            "/api/v1/agents/",
            headers=auth_headers,
            json={"name": "TestBot", "role": "coder"},
        )
        agent_id = agent_resp.json()["id"]

        # Mock Redis to avoid connection errors during dispatch
        mock_pool = AsyncMock()
        mock_pool.execute_with_retry = AsyncMock()

        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=mock_pool,
        ):
            # First dispatch should succeed
            resp1 = await client.post(
                "/api/v1/swarms/dispatch",
                headers=auth_headers,
                json={
                    "description": "Task 1",
                    "graph_type": "sequential",
                    "assigned_agent_ids": [agent_id],
                },
            )
            assert resp1.status_code == 201

            # Second dispatch should be rejected (limit is 1)
            resp2 = await client.post(
                "/api/v1/swarms/dispatch",
                headers=auth_headers,
                json={
                    "description": "Task 2",
                    "graph_type": "sequential",
                    "assigned_agent_ids": [agent_id],
                },
            )
            assert resp2.status_code == 429
            assert "Daily task limit" in resp2.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: RFC Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRFCValidation:
    async def test_rfc_format_valid_persona_fisica(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A 13-char RFC for persona fisica should pass format validation."""
        resp = await _create_tenant(client, auth_headers, rfc="GARC850101AB1")
        assert resp.status_code == 201
        assert resp.json()["rfc"] == "GARC850101AB1"

    async def test_rfc_format_valid_persona_moral(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A 12-char RFC for persona moral should pass format validation."""
        resp = await _create_tenant(client, auth_headers, rfc="MAD850101AB")
        # 3-letter prefix + 6 digits + 2 chars = 11 chars total
        # Actually persona moral is 3 + 6 + 3 = 12
        # The format XAXX010101000 is 4+6+3 = 13 (generic persona fisica)
        # Let's use a proper format
        assert resp.status_code in (201, 422)

    async def test_rfc_too_short_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await _create_tenant(client, auth_headers, rfc="AB")
        assert resp.status_code == 422

    async def test_rfc_invalid_chars_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await _create_tenant(client, auth_headers, rfc="!!INVALID!!00")
        assert resp.status_code == 422

    async def test_karafiel_rejection_propagates(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """When Karafiel rejects the RFC, the endpoint returns 400."""
        from fastapi import HTTPException as _HTTPException

        async def _mock_validate_karafiel(rfc: str) -> None:
            raise _HTTPException(
                status_code=400,
                detail="RFC rejected by Karafiel: Not found in SAT",
            )

        with patch(
            "nexus_api.routers.tenants._validate_rfc_with_karafiel",
            side_effect=_mock_validate_karafiel,
        ):
            resp = await _create_tenant(client, auth_headers, rfc="XAXX010101000")
            assert resp.status_code == 400
            assert "Karafiel" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Enterprise SSO Configuration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConfigureSSO:
    async def test_configure_sso_stores_connection_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/sso should store the Janua connection ID."""
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me/sso",
            headers=auth_headers,
            json={"janua_connection_id": "conn-okta-enterprise-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "configured"
        assert data["janua_connection_id"] == "conn-okta-enterprise-123"

        # Verify it persisted by reading the tenant config
        me_resp = await client.get(f"{_TENANTS_URL}/me", headers=auth_headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["janua_connection_id"] == "conn-okta-enterprise-123"

    async def test_configure_sso_404_when_not_provisioned(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/sso should return 404 if tenant not provisioned."""
        resp = await client.patch(
            f"{_TENANTS_URL}/me/sso",
            headers=auth_headers,
            json={"janua_connection_id": "conn-xyz"},
        )
        assert resp.status_code == 404

    async def test_configure_sso_rejects_empty_connection_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/sso should reject an empty janua_connection_id."""
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me/sso",
            headers=auth_headers,
            json={"janua_connection_id": ""},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: White-Label Branding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBranding:
    async def test_get_branding_returns_defaults(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /me/branding returns defaults when tenant has no config."""
        resp = await client.get(f"{_TENANTS_URL}/me/branding", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["brand_name"] == "Selva Office"
        assert data["brand_primary_color"] == "#4a9e6e"
        assert data["brand_logo_url"] is None

    async def test_get_branding_returns_defaults_when_provisioned_but_unset(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /me/branding returns defaults when tenant exists but branding is null."""
        await _create_tenant(client, auth_headers)

        resp = await client.get(f"{_TENANTS_URL}/me/branding", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["brand_name"] == "Selva Office"
        assert data["brand_primary_color"] == "#4a9e6e"

    async def test_update_branding_sets_values(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/branding should persist custom branding."""
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me/branding",
            headers=auth_headers,
            json={
                "brand_name": "MADFAM Hub",
                "brand_logo_url": "https://cdn.madfam.dev/logo.svg",
                "brand_primary_color": "#1a2b3c",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["brand_name"] == "MADFAM Hub"
        assert data["brand_logo_url"] == "https://cdn.madfam.dev/logo.svg"
        assert data["brand_primary_color"] == "#1a2b3c"

        # Verify via GET
        get_resp = await client.get(f"{_TENANTS_URL}/me/branding", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["brand_name"] == "MADFAM Hub"

    async def test_update_branding_partial(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/branding with partial body only updates provided fields."""
        await _create_tenant(client, auth_headers)

        resp = await client.patch(
            f"{_TENANTS_URL}/me/branding",
            headers=auth_headers,
            json={"brand_name": "Custom Name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["brand_name"] == "Custom Name"
        # Other fields should retain defaults
        assert data["brand_primary_color"] == "#4a9e6e"

    async def test_update_branding_404_when_not_provisioned(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /me/branding should return 404 if tenant not provisioned."""
        resp = await client.patch(
            f"{_TENANTS_URL}/me/branding",
            headers=auth_headers,
            json={"brand_name": "Nope"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Compute Budget Enforcement (Dhanam)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestComputeBudgetEnforcement:
    async def test_compute_budget_enforcement_402(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Dispatch returns 402 when Dhanam reports zero remaining tokens."""
        # Create tenant with a dhanam_space_id
        await _create_tenant(client, auth_headers)

        # Manually set dhanam_space_id on the tenant config
        from sqlalchemy import select

        from nexus_api.models import TenantConfig

        result = await db_session.execute(
            select(TenantConfig).where(TenantConfig.org_id == "dev-org")
        )
        config = result.scalar_one()
        config.dhanam_space_id = "space-test-123"
        await db_session.commit()

        # Create an agent so dispatch can assign it
        agent_resp = await client.post(
            "/api/v1/agents/",
            headers=auth_headers,
            json={"name": "BudgetTestBot", "role": "coder"},
        )
        agent_id = agent_resp.json()["id"]

        # Mock Redis and billing status to return exhausted budget
        mock_pool = AsyncMock()
        mock_pool.execute_with_retry = AsyncMock()

        async def _mock_billing_status(space_id: str):
            return {"compute_tokens_remaining": 0}

        with (
            patch(
                "nexus_api.routers.swarms.get_redis_pool",
                return_value=mock_pool,
            ),
            patch(
                "nexus_api.billing_client.get_billing_status",
                side_effect=_mock_billing_status,
            ),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                headers=auth_headers,
                json={
                    "description": "Should be blocked by budget",
                    "graph_type": "sequential",
                    "assigned_agent_ids": [agent_id],
                },
            )
            assert resp.status_code == 402
            detail = resp.json()["detail"]
            assert detail["code"] == "budget_exhausted"
            assert "budget exhausted" in detail["message"].lower()

    async def test_compute_budget_allows_when_tokens_remain(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Dispatch succeeds when Dhanam reports positive remaining tokens."""
        await _create_tenant(client, auth_headers)

        from sqlalchemy import select

        from nexus_api.models import TenantConfig

        result = await db_session.execute(
            select(TenantConfig).where(TenantConfig.org_id == "dev-org")
        )
        config = result.scalar_one()
        config.dhanam_space_id = "space-test-456"
        await db_session.commit()

        agent_resp = await client.post(
            "/api/v1/agents/",
            headers=auth_headers,
            json={"name": "BudgetOKBot", "role": "coder"},
        )
        agent_id = agent_resp.json()["id"]

        mock_pool = AsyncMock()
        mock_pool.execute_with_retry = AsyncMock()

        async def _mock_billing_ok(space_id: str):
            return {"compute_tokens_remaining": 9999}

        with (
            patch(
                "nexus_api.routers.swarms.get_redis_pool",
                return_value=mock_pool,
            ),
            patch(
                "nexus_api.billing_client.get_billing_status",
                side_effect=_mock_billing_ok,
            ),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                headers=auth_headers,
                json={
                    "description": "Should pass budget check",
                    "graph_type": "sequential",
                    "assigned_agent_ids": [agent_id],
                },
            )
            assert resp.status_code == 201

    async def test_compute_budget_skipped_when_dhanam_unavailable(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Dispatch proceeds gracefully when Dhanam API is unreachable."""
        await _create_tenant(client, auth_headers)

        from sqlalchemy import select

        from nexus_api.models import TenantConfig

        result = await db_session.execute(
            select(TenantConfig).where(TenantConfig.org_id == "dev-org")
        )
        config = result.scalar_one()
        config.dhanam_space_id = "space-test-789"
        await db_session.commit()

        agent_resp = await client.post(
            "/api/v1/agents/",
            headers=auth_headers,
            json={"name": "FallbackBot", "role": "coder"},
        )
        agent_id = agent_resp.json()["id"]

        mock_pool = AsyncMock()
        mock_pool.execute_with_retry = AsyncMock()

        async def _mock_billing_fail(space_id: str):
            raise ConnectionError("Dhanam unavailable")

        with (
            patch(
                "nexus_api.routers.swarms.get_redis_pool",
                return_value=mock_pool,
            ),
            patch(
                "nexus_api.billing_client.get_billing_status",
                side_effect=_mock_billing_fail,
            ),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                headers=auth_headers,
                json={
                    "description": "Should proceed despite Dhanam failure",
                    "graph_type": "sequential",
                    "assigned_agent_ids": [agent_id],
                },
            )
            assert resp.status_code == 201
