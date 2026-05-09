"""Tests for the /api/v1/tenant-identities router.

Covers:
    POST /api/v1/tenant-identities              — auth, create, duplicate
    GET  /api/v1/tenant-identities/resolve      — resolve by per-service id
    POST /api/v1/tenant-identities/{id}/validate — drift-check stub

Uses the in-memory SQLite from conftest.py.
"""

from __future__ import annotations

import httpx
import pytest

from nexus_api import config as _cfg_mod

WORKER_TOKEN = "dev-bypass"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WORKER_TOKEN}",
        "X-CSRF-Token": "test-csrf-token-fixed",
    }


def _payload(
    canonical_id: str = "madfam-test-001",
    *,
    janua_org_id: str | None = "madfam-test-001",
    dhanam_space_id: str | None = "sp-dhn-001",
    phyndcrm_tenant_id: str | None = "madfam-test-001",
    karafiel_org_id: str | None = "krf-001",
) -> dict:
    return {
        "canonical_id": canonical_id,
        "legal_name": "Innovaciones MADFAM Test SAS",
        "primary_contact_email": "ops@madfam.test",
        "janua_org_id": janua_org_id,
        "dhanam_space_id": dhanam_space_id,
        "phyndcrm_tenant_id": phyndcrm_tenant_id,
        "karafiel_org_id": karafiel_org_id,
        "resend_domain_ids": ["dmn_01"],
        "metadata": {"plan": "free", "voice_mode": "dyad_selva_plus_user"},
    }


@pytest.fixture(autouse=True)
def _ensure_worker_token() -> None:
    _cfg_mod.get_settings().worker_api_token = WORKER_TOKEN


@pytest.mark.asyncio
class TestCreate:
    async def test_requires_bearer(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/api/v1/tenant-identities", json=_payload())
        assert resp.status_code == 401

    async def test_rejects_wrong_token(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tenant-identities",
            json=_payload(),
            headers={
                "Authorization": "Bearer wrong",
                "X-CSRF-Token": "test-csrf-token-fixed",
            },
        )
        assert resp.status_code == 401

    async def test_creates_row(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tenant-identities",
            json=_payload("madfam-test-create"),
            headers=_headers(),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["canonical_id"] == "madfam-test-create"
        assert body["legal_name"] == "Innovaciones MADFAM Test SAS"
        assert body["dhanam_space_id"] == "sp-dhn-001"
        assert body["resend_domain_ids"] == ["dmn_01"]
        assert body["meta"]["plan"] == "free"
        assert "id" in body and body["id"]

    async def test_duplicate_canonical_id_returns_409(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/api/v1/tenant-identities",
            json=_payload("dup-id"),
            headers=_headers(),
        )
        resp2 = await client.post(
            "/api/v1/tenant-identities",
            json=_payload("dup-id"),
            headers=_headers(),
        )
        assert resp2.status_code == 409


@pytest.mark.asyncio
class TestResolve:
    async def test_resolves_by_canonical_id(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/api/v1/tenant-identities",
            json=_payload("resolve-canonical"),
            headers=_headers(),
        )
        resp = await client.get(
            "/api/v1/tenant-identities/resolve",
            params={"field": "canonical_id", "value": "resolve-canonical"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["canonical_id"] == "resolve-canonical"

    async def test_resolves_by_dhanam_space_id(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/api/v1/tenant-identities",
            json=_payload("resolve-by-dhanam", dhanam_space_id="sp-unique-xyz"),
            headers=_headers(),
        )
        resp = await client.get(
            "/api/v1/tenant-identities/resolve",
            params={"field": "dhanam_space_id", "value": "sp-unique-xyz"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["canonical_id"] == "resolve-by-dhanam"

    async def test_invalid_field_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/tenant-identities/resolve",
            params={"field": "not_a_field", "value": "x"},
            headers=_headers(),
        )
        assert resp.status_code == 400

    async def test_not_found_returns_404(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/tenant-identities/resolve",
            params={"field": "canonical_id", "value": "does-not-exist"},
            headers=_headers(),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestValidate:
    async def test_validates_existing_tenant(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/api/v1/tenant-identities",
            json=_payload("validate-me"),
            headers=_headers(),
        )
        resp = await client.post(
            "/api/v1/tenant-identities/validate-me/validate",
            headers=_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["canonical_id"] == "validate-me"
        assert body["services_checked"] == 4  # janua+dhanam+phyndcrm+karafiel
        assert body["drifts"] == []

    async def test_validate_unknown_returns_404(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tenant-identities/nope/validate",
            headers=_headers(),
        )
        assert resp.status_code == 404
