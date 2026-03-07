"""Tests for the Phyne-CRM adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoswarm_inference.adapters.crm import PhyneCRMAdapter
from autoswarm_inference.adapters.crm_types import (
    PhyneActivity,
    PhyneContact,
    PhyneDashboard,
    PhyneLead,
    PhyneLeadScore,
    PhyneUnifiedProfile,
)


def _mock_response(data: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"result": {"data": data}}
    return resp


class TestPhyneCRMAdapter:
    """Phyne-CRM adapter methods."""

    @pytest.mark.asyncio
    async def test_list_contacts(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response([
            {"id": "c1", "name": "Alice", "email": "alice@example.com"},
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="test-token")
            contacts = await adapter.list_contacts()

        assert len(contacts) == 1
        assert contacts[0].name == "Alice"

    @pytest.mark.asyncio
    async def test_get_unified_profile(self) -> None:
        profile_data = {
            "contact": {"id": "c1", "name": "Bob", "email": "bob@test.com"},
            "leads": [{"id": "l1", "contact_id": "c1", "stage_id": "s1"}],
            "activities": [],
            "billing_status": "active",
            "total_revenue": 5000.0,
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(profile_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="t")
            profile = await adapter.get_unified_profile("c1")

        assert isinstance(profile, PhyneUnifiedProfile)
        assert profile.contact.name == "Bob"
        assert len(profile.leads) == 1
        assert profile.total_revenue == 5000.0

    @pytest.mark.asyncio
    async def test_create_activity(self) -> None:
        activity_data = {
            "id": "a1",
            "type": "email",
            "title": "Follow up",
            "status": "pending",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(activity_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="t")
            activity = await adapter.create_activity(
                type="email",
                title="Follow up",
                entity_type="contact",
                entity_id="c1",
            )

        assert isinstance(activity, PhyneActivity)
        assert activity.id == "a1"

    @pytest.mark.asyncio
    async def test_compute_lead_score(self) -> None:
        score_data = {
            "lead_id": "l1",
            "score": 85.5,
            "factors": {"engagement": 0.9, "fit": 0.8},
            "recommendation": "High priority",
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(score_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="t")
            score = await adapter.compute_lead_score("l1")

        assert isinstance(score, PhyneLeadScore)
        assert score.score == 85.5

    @pytest.mark.asyncio
    async def test_auth_header_propagation(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response([])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="my-jwt-token")
            await adapter.list_contacts()

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer my-jwt-token"

    @pytest.mark.asyncio
    async def test_timeout_configuration(self) -> None:
        adapter = PhyneCRMAdapter(
            base_url="http://crm:3000", token="t", timeout=5.0
        )
        assert adapter.timeout == 5.0

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(httpx.ConnectError),
        ):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000")
            await adapter.list_contacts()

    @pytest.mark.asyncio
    async def test_list_leads(self) -> None:
        leads_data = [
            {"id": "l1", "contact_id": "c1", "stage_id": "s1", "status": "open"},
            {"id": "l2", "contact_id": "c2", "stage_id": "s2", "status": "open"},
        ]
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(leads_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000")
            leads = await adapter.list_leads(status="open")

        assert len(leads) == 2
        assert all(isinstance(l, PhyneLead) for l in leads)

    @pytest.mark.asyncio
    async def test_get_dashboard(self) -> None:
        dash_data = {
            "total_contacts": 42,
            "total_leads": 15,
            "open_activities": 8,
            "pipeline_value": 125000.0,
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(dash_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000")
            dashboard = await adapter.get_dashboard()

        assert isinstance(dashboard, PhyneDashboard)
        assert dashboard.total_contacts == 42

    @pytest.mark.asyncio
    async def test_no_auth_header_when_token_empty(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response([])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_inference.adapters.crm.httpx.AsyncClient", return_value=mock_client):
            adapter = PhyneCRMAdapter(base_url="http://crm:3000", token="")
            await adapter.list_contacts()

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs[1]["headers"]
        assert "Authorization" not in headers
