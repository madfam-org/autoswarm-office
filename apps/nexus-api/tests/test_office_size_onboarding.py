"""Tests for the office-size onboarding endpoints (migration 0041)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import TenantConfig


@pytest.mark.asyncio
class TestOfficeSize:
    async def test_defaults_to_null(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/onboarding/office-size", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["office_size"] is None

    async def test_put_upserts_and_persists(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """PUT creates the tenant_config if absent (onboarding runs first)."""
        resp = await client.put(
            "/api/v1/onboarding/office-size",
            headers=auth_headers,
            json={"office_size": "21-50"},
        )
        assert resp.status_code == 200
        assert resp.json()["office_size"] == "21-50"

        # Round-trips through GET.
        got = await client.get("/api/v1/onboarding/office-size", headers=auth_headers)
        assert got.json()["office_size"] == "21-50"

        # And is on the row (dev-org from the auth bypass).
        db_session.expire_all()
        row = await db_session.execute(
            select(TenantConfig).where(TenantConfig.org_id == "dev-org")
        )
        assert row.scalar_one().office_size == "21-50"

    async def test_put_overwrites_previous_choice(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.put(
            "/api/v1/onboarding/office-size",
            headers=auth_headers,
            json={"office_size": "1-10"},
        )
        resp = await client.put(
            "/api/v1/onboarding/office-size",
            headers=auth_headers,
            json={"office_size": "81-100"},
        )
        assert resp.json()["office_size"] == "81-100"

    async def test_rejects_unknown_band(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.put(
            "/api/v1/onboarding/office-size",
            headers=auth_headers,
            json={"office_size": "500-goojillion"},
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/onboarding/office-size")
        assert resp.status_code == 401
