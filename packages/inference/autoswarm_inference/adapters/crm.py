"""Phyne-CRM adapter for tRPC API integration."""

from __future__ import annotations

import logging

import httpx

from .crm_types import (
    PhyneActivity,
    PhyneContact,
    PhyneDashboard,
    PhyneLead,
    PhyneLeadScore,
    PhyneUnifiedProfile,
)

logger = logging.getLogger(__name__)


class PhyneCRMAdapter:
    """Async client wrapping the Phyne-CRM tRPC endpoints.

    Uses httpx.AsyncClient for HTTP calls with Bearer token auth.
    Parses SuperJSON-style responses where applicable.
    """

    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _trpc_url(self, procedure: str) -> str:
        return f"{self.base_url}/api/trpc/{procedure}"

    async def _get(self, procedure: str, input_data: dict | None = None) -> dict:
        """Execute a tRPC query (GET)."""
        params = {}
        if input_data:
            import json

            params["input"] = json.dumps(input_data)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                self._trpc_url(procedure),
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            # tRPC wraps results in {"result": {"data": ...}}
            return data.get("result", {}).get("data", data)

    async def _mutate(self, procedure: str, input_data: dict) -> dict:
        """Execute a tRPC mutation (POST)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self._trpc_url(procedure),
                headers=self._headers(),
                json=input_data,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("data", data)

    # -- Contact operations ---------------------------------------------------

    async def list_contacts(self) -> list[PhyneContact]:
        data = await self._get("contacts.list")
        if isinstance(data, list):
            return [PhyneContact(**c) for c in data]
        return []

    async def get_contact(self, contact_id: str) -> PhyneContact:
        data = await self._get("contacts.getById", {"id": contact_id})
        return PhyneContact(**data)

    # -- Lead operations ------------------------------------------------------

    async def list_leads(self, status: str | None = None) -> list[PhyneLead]:
        input_data = {}
        if status:
            input_data["status"] = status
        data = await self._get("leads.list", input_data or None)
        if isinstance(data, list):
            return [PhyneLead(**l) for l in data]
        return []

    async def move_lead_stage(self, lead_id: str, stage_id: str) -> PhyneLead:
        data = await self._mutate(
            "leads.moveToStage", {"id": lead_id, "stageId": stage_id}
        )
        return PhyneLead(**data)

    # -- Activity operations --------------------------------------------------

    async def create_activity(
        self,
        *,
        type: str,
        title: str,
        description: str = "",
        entity_type: str = "",
        entity_id: str = "",
    ) -> PhyneActivity:
        data = await self._mutate(
            "activities.create",
            {
                "type": type,
                "title": title,
                "description": description,
                "entityType": entity_type,
                "entityId": entity_id,
            },
        )
        return PhyneActivity(**data)

    async def complete_activity(self, activity_id: str) -> PhyneActivity:
        data = await self._mutate(
            "activities.complete", {"id": activity_id}
        )
        return PhyneActivity(**data)

    async def list_activities(
        self, entity_type: str, entity_id: str
    ) -> list[PhyneActivity]:
        data = await self._get(
            "activities.listForEntity",
            {"type": entity_type, "id": entity_id},
        )
        if isinstance(data, list):
            return [PhyneActivity(**a) for a in data]
        return []

    # -- Unified profile ------------------------------------------------------

    async def get_unified_profile(self, contact_id: str) -> PhyneUnifiedProfile:
        data = await self._get(
            "unifiedProfile.getProfile", {"contactId": contact_id}
        )
        return PhyneUnifiedProfile(**data)

    # -- Lead scoring ---------------------------------------------------------

    async def compute_lead_score(self, lead_id: str) -> PhyneLeadScore:
        data = await self._get(
            "leadScoring.compute", {"leadId": lead_id}
        )
        return PhyneLeadScore(**data)

    # -- Dashboard ------------------------------------------------------------

    async def get_dashboard(self) -> PhyneDashboard:
        data = await self._get("analytics.dashboardSummary")
        return PhyneDashboard(**data)
