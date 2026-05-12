"""PhyndCRM tenant bootstrap tools.

Each onboarded tenant needs a ``tenant_configs`` row seeded with voice_mode
+ default pipeline + seed user. This module encapsulates that bootstrap
sequence so a tenant isn't born half-provisioned.

API base: ``PHYND_CRM_URL`` (default ``http://phynd-crm-web.phynd-crm.svc.cluster.local``
for in-cluster, ``https://crm.madfam.io`` from outside).
Auth: ``PHYND_CRM_FEDERATION_TOKEN`` — service-to-service token that bypasses
Auth.js session check and opens service-role scopes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

PHYND_CRM_URL = os.environ.get("PHYND_CRM_URL", "http://phynd-crm-web.phynd-crm.svc.cluster.local")
PHYND_CRM_TOKEN = os.environ.get(
    "PHYND_CRM_FEDERATION_TOKEN", os.environ.get("PHYND_CRM_TOKEN", "")
)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {PHYND_CRM_TOKEN}",
        "Content-Type": "application/json",
    }


def _creds_check() -> str | None:
    if not PHYND_CRM_TOKEN:
        return "PHYND_CRM_FEDERATION_TOKEN must be set."
    return None


async def _trpc(procedure: str, input_data: dict[str, Any] | None = None) -> tuple[int, Any]:
    """Invoke a PhyndCRM tRPC procedure via the HTTP adapter."""
    url = f"{PHYND_CRM_URL.rstrip('/')}/api/trpc/{procedure}"
    async with httpx.AsyncClient(timeout=30) as client:
        if input_data is None:
            resp = await client.get(url, headers=_headers())
        else:
            resp = await client.post(
                url,
                headers=_headers(),
                json={"json": input_data},
            )
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text


def _ok(s: int) -> bool:
    return 200 <= s < 300


def _trpc_err(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            return err.get("json", {}).get("message") or err.get("message") or str(err)
        return str(err)
    return str(body)


class PhyndcrmTenantCreateTool(BaseTool):
    """Bootstrap a tenant_configs row with voice_mode + default pipeline."""

    name = "phyndcrm_tenant_create"
    description = (
        "Create a PhyndCRM tenant_configs row for a new customer. Seeds "
        "voice_mode (for outbound email identity rules) and marks onboarding "
        "incomplete. Follow with phyndcrm_pipeline_bootstrap to create the "
        "default sales pipeline."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "Stable tenant id — typically the Janua org_id.",
                },
                "legal_name": {"type": "string"},
                "primary_contact_email": {"type": "string"},
                "voice_mode": {
                    "type": "string",
                    "enum": ["user_direct", "dyad_selva_plus_user", "agent_identified"],
                    "description": "Outbound voice-mode per the consent ledger "
                    "legal framework. Defaults to NULL (onboarding incomplete).",
                },
            },
            "required": ["tenant_id", "legal_name", "primary_contact_email"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        payload = {
            "tenant_id": kwargs["tenant_id"],
            "legal_name": kwargs["legal_name"],
            "primary_contact_email": kwargs["primary_contact_email"],
        }
        if kwargs.get("voice_mode"):
            payload["voice_mode"] = kwargs["voice_mode"]
        try:
            status, body = await _trpc("tenants.create", payload)
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            data = (body or {}).get("result", {}).get("data", {}).get("json", {})
            return ToolResult(
                success=True,
                output=f"Tenant bootstrapped: {kwargs['tenant_id']}",
                data={"tenant_id": kwargs["tenant_id"], "config": data},
            )
        except Exception as e:
            logger.error("phyndcrm_tenant_create failed: %s", e)
            return ToolResult(success=False, error=str(e))


class PhyndcrmPipelineBootstrapTool(BaseTool):
    """Create a named sales pipeline with default stages."""

    name = "phyndcrm_pipeline_bootstrap"
    description = (
        "Create a sales pipeline with default stages: "
        "New → Qualified → Proposal → Negotiation → Won/Lost. "
        "Every tenant needs at least one pipeline to start using the CRM. "
        "Use phyndcrm_pipeline_add_stage afterwards if the tenant needs "
        "a domain-specific stage (e.g. 'Design Review' for agency workflows)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "name": {"type": "string", "default": "Default Sales Pipeline"},
                "is_default": {"type": "boolean", "default": True},
                "stages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional override — list of "
                    "{name, probability, order} items. Default ladder is "
                    "provided if omitted.",
                },
            },
            "required": ["tenant_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        default_stages = [
            {"name": "New", "probability": 10, "order": 1},
            {"name": "Qualified", "probability": 30, "order": 2},
            {"name": "Proposal", "probability": 60, "order": 3},
            {"name": "Negotiation", "probability": 80, "order": 4},
            {"name": "Won", "probability": 100, "order": 5},
            {"name": "Lost", "probability": 0, "order": 6},
        ]
        payload = {
            "tenantId": kwargs["tenant_id"],
            "name": kwargs.get("name", "Default Sales Pipeline"),
            "isDefault": kwargs.get("is_default", True),
            "stages": kwargs.get("stages") or default_stages,
        }
        try:
            status, body = await _trpc("pipelines.createWithStages", payload)
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            data = (body or {}).get("result", {}).get("data", {}).get("json", {})
            return ToolResult(
                success=True,
                output=f"Pipeline created with {len(payload['stages'])} stage(s).",
                data={
                    "pipeline_id": data.get("id"),
                    "tenant_id": kwargs["tenant_id"],
                    "stage_count": len(payload["stages"]),
                },
            )
        except Exception as e:
            logger.error("phyndcrm_pipeline_bootstrap failed: %s", e)
            return ToolResult(success=False, error=str(e))


class PhyndcrmTenantConfigGetTool(BaseTool):
    """Read a tenant's full PhyndCRM config (voice_mode + onboarding state)."""

    name = "phyndcrm_tenant_config_get"
    description = (
        "Fetch the tenant_configs row for a tenant. Useful for detecting "
        "incomplete onboarding (voice_mode NULL) or verifying config after "
        "a bootstrap run."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"tenant_id": {"type": "string"}},
            "required": ["tenant_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        tid = kwargs["tenant_id"]
        try:
            input_enc = json.dumps({"json": {"tenantId": tid}})
            url = f"/api/trpc/tenants.config?input={input_enc}"
            # Use raw GET for tRPC query
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{PHYND_CRM_URL.rstrip('/')}{url}", headers=_headers())
                status = resp.status_code
                body = resp.json()
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            data = body.get("result", {}).get("data", {}).get("json", {})
            return ToolResult(
                success=True,
                output=f"Tenant {tid}: voice_mode={data.get('voice_mode')}",
                data=data,
            )
        except Exception as e:
            logger.error("phyndcrm_tenant_config_get failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_phyndcrm_provisioning_tools() -> list[BaseTool]:
    return [
        PhyndcrmTenantCreateTool(),
        PhyndcrmPipelineBootstrapTool(),
        PhyndcrmTenantConfigGetTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    PhyndcrmTenantCreateTool,
    PhyndcrmPipelineBootstrapTool,
):
    _cls.audience = Audience.PLATFORM
