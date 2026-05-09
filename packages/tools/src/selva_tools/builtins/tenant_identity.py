"""Tenant identity reconciliation — the cross-cutting ID map.

Every onboarded tenant has identities in multiple services:
- Janua org_id
- Dhanam space_id
- PhyndCRM tenant_id
- Karafiel org_id
- Resend domain_id(s)
- Cloudflare zone_id(s) (for bring-your-own-domain tenants)
- Selva Office seat + org assignment

When any one of these drifts (deleted in one service, still active in
another), we end up with orphan data. This module owns a single
``tenant_identities`` table in the nexus-api database that stores the
mapping, plus three operations:

- ``tenant_resolve`` — given any one id, return all the others
- ``tenant_create_identity_record`` — write a new row with all known ids
- ``tenant_validate_consistency`` — check each id still resolves in its
  home service, flag drift

Env: ``NEXUS_API_URL`` + ``WORKER_API_TOKEN`` — same surface as HITL tools.
The ``tenant_identities`` schema is created by migration ``0024_tenant_identities``
(see apps/nexus-api/alembic/versions/).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

NEXUS_API_URL = os.environ.get("NEXUS_API_URL", "http://nexus-api.autoswarm.svc.cluster.local")
WORKER_API_TOKEN = os.environ.get("WORKER_API_TOKEN", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WORKER_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _creds_check() -> str | None:
    if not WORKER_API_TOKEN:
        return "WORKER_API_TOKEN must be set."
    return None


async def _request(method: str, path: str, json_body: dict[str, Any] | None = None):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method,
            f"{NEXUS_API_URL.rstrip('/')}{path}",
            headers=_headers(),
            json=json_body,
        )
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text


def _ok(s: int) -> bool:
    return 200 <= s < 300


def _err(s: int, body: Any) -> str:
    if isinstance(body, dict):
        return body.get("detail") or body.get("message") or str(body)
    return f"HTTP {s}: {body}"


class TenantCreateIdentityRecordTool(BaseTool):
    """Create a tenant_identities row linking all known per-service IDs."""

    name = "tenant_create_identity_record"
    description = (
        "Create a row in the central tenant_identities table mapping a "
        "single tenant to its id in every service. Call this at the very "
        "end of an onboarding flow when every primitive has succeeded. "
        "Downstream reconciliation + offboarding tools follow this row "
        "as the source of truth for 'which services hold state for this "
        "tenant'."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "canonical_id": {
                    "type": "string",
                    "description": "Usually the Janua org_id — the tenant's "
                    "stable cross-service identifier.",
                },
                "legal_name": {"type": "string"},
                "primary_contact_email": {"type": "string"},
                "janua_org_id": {"type": "string"},
                "dhanam_space_id": {"type": "string"},
                "phyndcrm_tenant_id": {"type": "string"},
                "karafiel_org_id": {"type": "string"},
                "resend_domain_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "cloudflare_zone_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "selva_office_seat_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "r2_bucket_names": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "metadata": {"type": "object"},
            },
            "required": ["canonical_id", "legal_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        try:
            status, body = await _request(
                "POST",
                "/api/v1/tenant-identities",
                json_body=kwargs,
            )
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=f"Tenant identity record created: {kwargs['canonical_id']}",
                data={
                    "canonical_id": kwargs["canonical_id"],
                    "id": body.get("id"),
                },
            )
        except Exception as e:
            logger.error("tenant_create_identity_record failed: %s", e)
            return ToolResult(success=False, error=str(e))


class TenantResolveTool(BaseTool):
    """Given any one per-service id, return the full identity map."""

    name = "tenant_resolve"
    description = (
        "Look up a tenant_identities row by any one of its per-service ids. "
        "Given a PhyndCRM tenant_id, returns the Janua org_id / Dhanam "
        "space_id / Karafiel org_id / etc. Essential for cross-service "
        "operations that start from one service's perspective."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "lookup_field": {
                    "type": "string",
                    "enum": [
                        "canonical_id",
                        "janua_org_id",
                        "dhanam_space_id",
                        "phyndcrm_tenant_id",
                        "karafiel_org_id",
                    ],
                },
                "lookup_value": {"type": "string"},
            },
            "required": ["lookup_field", "lookup_value"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        field = kwargs["lookup_field"]
        value = kwargs["lookup_value"]
        try:
            status, body = await _request(
                "GET",
                f"/api/v1/tenant-identities/resolve?field={field}&value={value}",
            )
            if status == 404:
                return ToolResult(
                    success=False,
                    error=f"no tenant found with {field}={value}",
                )
            if not _ok(status):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=f"Resolved: canonical_id={body.get('canonical_id')}",
                data=body,
            )
        except Exception as e:
            logger.error("tenant_resolve failed: %s", e)
            return ToolResult(success=False, error=str(e))


class TenantValidateConsistencyTool(BaseTool):
    """Check each per-service id still exists in its home service."""

    name = "tenant_validate_consistency"
    description = (
        "For one tenant's identity record, ask each home service whether "
        "the recorded id still exists. Returns a per-service healthy/drifted "
        "verdict and a summary of any gaps. Run weekly as a drift check; "
        "also run before any bulk operation that assumes the tenant is "
        "fully alive across services."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"canonical_id": {"type": "string"}},
            "required": ["canonical_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        cid = kwargs["canonical_id"]
        try:
            status, body = await _request("POST", f"/api/v1/tenant-identities/{cid}/validate")
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            drifts = body.get("drifts") or []
            return ToolResult(
                success=True,
                output=(
                    f"{cid}: "
                    f"{len(drifts)} drift(s) across "
                    f"{body.get('services_checked', 0)} service(s)."
                ),
                data=body,
            )
        except Exception as e:
            logger.error("tenant_validate_consistency failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_tenant_identity_tools() -> list[BaseTool]:
    return [
        TenantCreateIdentityRecordTool(),
        TenantResolveTool(),
        TenantValidateConsistencyTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    TenantCreateIdentityRecordTool,
    TenantResolveTool,
    TenantValidateConsistencyTool,
):
    _cls.audience = Audience.PLATFORM
