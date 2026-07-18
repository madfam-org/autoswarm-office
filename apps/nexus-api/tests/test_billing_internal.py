"""Tests for the billing internal router (worker-to-API metering).

These endpoints are authenticated (RFC 0034 P0 / D6): they write and read the
compute-token ledger, so every call must present a valid token.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
class TestRecordUsage:
    async def test_record_success(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 100},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "recorded"

    async def test_record_matching_body_org_tolerated(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Older workers still send org_id; a value matching the authenticated
        scope keeps working during the transition."""
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 100, "org_id": "dev-org"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def test_record_cross_org_body_is_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A caller must not be able to debit another tenant's bucket by
        naming it in the body (tenant-scoping invariant, AGENTS.md)."""
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 100, "org_id": "victim-org"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    async def test_missing_required_fields(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_amount_must_be_positive(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_unauthenticated_record_is_rejected(self, client: httpx.AsyncClient) -> None:
        """RFC 0034 P0: the ledger write is no longer network-only — an
        unauthenticated caller can't forge billing entries."""
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 100, "org_id": "default"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestCheckBudget:
    async def test_check_budget_default(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_limit" in data
        assert "used" in data
        assert "remaining" in data
        assert "over_budget" in data
        assert data["over_budget"] is False

    async def test_budget_after_recording(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 50},
            headers=auth_headers,
        )
        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["used"] == 50

    async def test_check_budget_cross_org_body_is_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """One tenant must not be able to read another tenant's spend position."""
        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={"org_id": "victim-org"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    async def test_unauthenticated_check_is_rejected(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={"org_id": "default"},
        )
        assert resp.status_code == 401
