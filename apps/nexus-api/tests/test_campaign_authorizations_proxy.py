"""Tests for the owner campaign-authorization proxy (PhyndCRM money-gate).

The proxy is a thin, honest bridge: unconfigured -> 503 (never an empty
queue), upstream tRPC errors surface with their message, rejection
requires a written reason, and the decision is attributed to the
authenticated admin's identity (phynd records it as
``"<operator> (via service:selva)"``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nexus_api.services import phynd_campaign_authorizations as bridge

_SVC = "nexus_api.services.phynd_campaign_authorizations"


class TestUnconfigured:
    @pytest.mark.asyncio
    async def test_pending_returns_503_when_bridge_unconfigured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Test settings carry no PHYND_CRM_URL / token -> honest 503.
        resp = await client.get("/api/v1/campaigns/authorizations/pending", headers=auth_headers)
        assert resp.status_code == 503
        assert "PHYND_CRM_FEDERATION_TOKEN" in resp.json()["detail"]


class TestPendingAndPreview:
    @pytest.mark.asyncio
    async def test_pending_proxies_rows(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rows = [{"authorization": {"id": "auth-1"}, "campaign": {"id": "camp-1"}}]
        with patch(f"{_SVC}.list_pending", new=AsyncMock(return_value=rows)):
            resp = await client.get(
                "/api/v1/campaigns/authorizations/pending", headers=auth_headers
            )
        assert resp.status_code == 200
        assert resp.json() == {"pending": rows}

    @pytest.mark.asyncio
    async def test_preview_proxies_payload(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        preview = {"authorization": {"id": "auth-1"}, "stale": False, "rendered": []}
        with patch(f"{_SVC}.get_preview", new=AsyncMock(return_value=preview)) as mock_get:
            resp = await client.get(
                "/api/v1/campaigns/authorizations/auth-1/preview", headers=auth_headers
            )
        assert resp.status_code == 200
        assert resp.json()["stale"] is False
        mock_get.assert_awaited_once_with("auth-1")

    @pytest.mark.asyncio
    async def test_upstream_error_surfaces_message(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with patch(
            f"{_SVC}.get_preview",
            new=AsyncMock(
                side_effect=bridge.PhyndAuthorizationsError("CampaignAuthorization not found", 404)
            ),
        ):
            resp = await client.get(
                "/api/v1/campaigns/authorizations/missing/preview", headers=auth_headers
            )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


class TestDecide:
    @pytest.mark.asyncio
    async def test_reject_without_note_is_422_before_bridge_call(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with patch(f"{_SVC}.decide", new=AsyncMock()) as mock_decide:
            resp = await client.post(
                "/api/v1/campaigns/authorizations/auth-1/decide",
                headers=auth_headers,
                json={"decision": "rejected", "note": "   "},
            )
        assert resp.status_code == 422
        mock_decide.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorize_attributes_authenticated_operator(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        record = {
            "id": "auth-1",
            "status": "authorized",
            "decidedBy": "dev@selva.local (via service:selva)",
            "decidedVia": "selva",
        }
        with patch(f"{_SVC}.decide", new=AsyncMock(return_value=record)) as mock_decide:
            resp = await client.post(
                "/api/v1/campaigns/authorizations/auth-1/decide",
                headers=auth_headers,
                json={"decision": "authorized"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "authorized"
        kwargs = mock_decide.await_args.kwargs
        assert kwargs["authorization_id"] == "auth-1"
        assert kwargs["decision"] == "authorized"
        # Operator comes from the authenticated session (dev bypass user),
        # never from the request body.
        assert kwargs["operator"] == "dev@selva.local"
        assert kwargs["note"] is None

    @pytest.mark.asyncio
    async def test_reject_with_note_relays_note(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        record = {"id": "auth-1", "status": "rejected"}
        with patch(f"{_SVC}.decide", new=AsyncMock(return_value=record)) as mock_decide:
            resp = await client.post(
                "/api/v1/campaigns/authorizations/auth-1/decide",
                headers=auth_headers,
                json={"decision": "rejected", "note": "Cifras no cuadran"},
            )
        assert resp.status_code == 200
        assert mock_decide.await_args.kwargs["note"] == "Cifras no cuadran"


class TestRequestFresh:
    @pytest.mark.asyncio
    async def test_request_fresh_relays_campaign_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        record = {"id": "auth-2", "campaignId": "camp-1", "status": "pending"}
        with patch(f"{_SVC}.request_fresh", new=AsyncMock(return_value=record)) as mock_req:
            resp = await client.post(
                "/api/v1/campaigns/authorizations/request",
                headers=auth_headers,
                json={"campaign_id": "camp-1"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "auth-2"
        mock_req.assert_awaited_once_with("camp-1")
