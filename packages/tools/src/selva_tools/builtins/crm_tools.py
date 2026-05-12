"""CRM tools for the Growth Node — lead management and pipeline actions."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

PHYND_CRM_URL = os.environ.get("PHYND_CRM_URL", "")
PHYND_CRM_API_KEY = os.environ.get("PHYND_CRM_API_KEY", "")


def _crm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if PHYND_CRM_API_KEY:
        headers["Authorization"] = f"Bearer {PHYND_CRM_API_KEY}"
    return headers


class CreateLeadTool(BaseTool):
    """Create a new lead in PhyndCRM from a contact.

    Used by Growth Node agents (Heraldo, Nexo) to capture new prospects
    into the sales pipeline. Category: CRM_UPDATE.
    """

    name = "create_lead"
    description = (
        "Create a new sales lead in PhyndCRM. "
        "Use when you identify a potential customer that should enter the pipeline."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Full name of the contact"},
                "contact_email": {"type": "string", "description": "Email address"},
                "source": {
                    "type": "string",
                    "description": "Lead source (e.g., 'website', 'referral', 'content', 'outbound')",  # noqa: E501
                    "default": "agent_generated",
                },
                "notes": {
                    "type": "string",
                    "description": "Context about why this is a lead",
                    "default": "",
                },
            },
            "required": ["contact_name", "contact_email"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PHYND_CRM_URL:
            return ToolResult(success=False, error="PHYND_CRM_URL not configured")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{PHYND_CRM_URL}/api/v1/leads",
                    headers=_crm_headers(),
                    json={
                        "contactName": kwargs.get("contact_name", ""),
                        "contactEmail": kwargs.get("contact_email", ""),
                        "source": kwargs.get("source", "agent_generated"),
                        "notes": kwargs.get("notes", ""),
                        "status": "new",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            return ToolResult(
                success=True,
                output=f"Lead created: {data.get('id', 'unknown')} for {kwargs.get('contact_email', '')}",  # noqa: E501
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Lead creation failed: {exc}")


class UpdateLeadStatusTool(BaseTool):
    """Update a lead's status in PhyndCRM.

    Advances leads through the pipeline: new → qualified → contacted →
    negotiation → won/lost. Category: CRM_UPDATE.
    """

    name = "update_lead_status"
    description = (
        "Update the status of a lead in PhyndCRM. Use to advance leads through the sales pipeline."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "ID of the lead to update"},
                "status": {
                    "type": "string",
                    "description": "New status (new, qualified, contacted, negotiation, won, lost)",
                    "enum": ["new", "qualified", "contacted", "negotiation", "won", "lost"],
                },
                "notes": {
                    "type": "string",
                    "description": "Reason for status change",
                    "default": "",
                },
            },
            "required": ["lead_id", "status"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PHYND_CRM_URL:
            return ToolResult(success=False, error="PHYND_CRM_URL not configured")

        lead_id = kwargs.get("lead_id", "")
        status = kwargs.get("status", "")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.patch(
                    f"{PHYND_CRM_URL}/api/v1/leads/{lead_id}/status",
                    headers=_crm_headers(),
                    json={"status": status, "notes": kwargs.get("notes", "")},
                )
                resp.raise_for_status()
                data = resp.json()

            return ToolResult(
                success=True,
                output=f"Lead {lead_id} status updated to '{status}'",
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Lead status update failed: {exc}")


class CreateActivityTool(BaseTool):
    """Log an activity against a CRM entity (lead, contact, opportunity).

    Creates an audit trail of agent interactions with prospects. Category: CRM_UPDATE.
    """

    name = "create_crm_activity"
    description = (
        "Log an activity (call, email, meeting, note) against a CRM entity. "
        "Use to track agent interactions with leads and contacts."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Type of entity (lead, contact, opportunity)",
                    "enum": ["lead", "contact", "opportunity"],
                },
                "entity_id": {"type": "string", "description": "ID of the entity"},
                "activity_type": {
                    "type": "string",
                    "description": "Type of activity (email, call, meeting, note, task)",
                    "default": "note",
                },
                "notes": {"type": "string", "description": "Activity details"},
            },
            "required": ["entity_type", "entity_id", "notes"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PHYND_CRM_URL:
            return ToolResult(success=False, error="PHYND_CRM_URL not configured")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{PHYND_CRM_URL}/api/v1/activities",
                    headers=_crm_headers(),
                    json={
                        "entityType": kwargs.get("entity_type", "lead"),
                        "entityId": kwargs.get("entity_id", ""),
                        "activityType": kwargs.get("activity_type", "note"),
                        "notes": kwargs.get("notes", ""),
                        "performedBy": "selva-agent",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            return ToolResult(
                success=True,
                output=f"Activity logged for {kwargs.get('entity_type', '')} {kwargs.get('entity_id', '')}",  # noqa: E501
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Activity creation failed: {exc}")
