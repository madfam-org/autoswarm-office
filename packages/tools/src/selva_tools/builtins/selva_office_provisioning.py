"""Selva Office seat + department provisioning.

Tools for bootstrapping a tenant's Selva Office workspace once the
tenant has been provisioned everywhere else (Janua auth + Dhanam billing
+ PhyndCRM + Karafiel). These land a tenant's user(s) inside the office
UI with appropriate department assignments.

Three tools:

- ``selva_office_seat_create`` — provision a seat (user) in the office
  under a tenant's org. Optionally department-assign at create time.
- ``selva_office_seat_assign_department`` — move an existing seat to a
  different department (or between zones within the same department).
- ``selva_office_seat_revoke`` — revoke a seat (offboard a team member).
  HITL-gated — revoking a seat removes the user's entire AutoSwarm
  access history from their view.

Env: ``NEXUS_API_URL`` + ``WORKER_API_TOKEN`` — same surface as HITL
tools + tenant_identity tools.
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
HTTP_TIMEOUT = 15.0


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
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
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


class SelvaOfficeSeatCreateTool(BaseTool):
    """Provision a seat in the office for a tenant's user."""

    name = "selva_office_seat_create"
    description = (
        "Create an office seat for a tenant user. The seat binds a Janua "
        "user sub to a tenant org_id, surfaces that user in the office "
        "UI, and optionally places them in a department zone. Idempotent "
        "per (org_id, user_sub) — calling twice returns the same seat."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "org_id": {
                    "type": "string",
                    "description": "Tenant canonical id (Janua org_id).",
                },
                "user_sub": {
                    "type": "string",
                    "description": "Janua user sub (JWT subject claim).",
                },
                "display_name": {"type": "string"},
                "email": {"type": "string"},
                "role": {
                    "type": "string",
                    "enum": ["operator", "manager", "admin", "viewer"],
                    "default": "operator",
                },
                "department_id": {
                    "type": "string",
                    "description": "Optional initial department assignment "
                    "(e.g. 'dept-engineering', 'dept-crm').",
                },
                "metadata": {"type": "object"},
            },
            "required": ["org_id", "user_sub", "display_name", "email"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        payload = {
            "org_id": kwargs["org_id"],
            "user_sub": kwargs["user_sub"],
            "display_name": kwargs["display_name"],
            "email": kwargs["email"],
            "role": kwargs.get("role", "operator"),
        }
        if kwargs.get("department_id"):
            payload["department_id"] = kwargs["department_id"]
        if kwargs.get("metadata"):
            payload["metadata"] = kwargs["metadata"]
        try:
            status, body = await _request("POST", "/api/v1/office/seats", json_body=payload)
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=(
                    f"Seat created: {body.get('seat_id')} for "
                    f"{kwargs['display_name']} @ {kwargs['org_id']}"
                ),
                data={
                    "seat_id": body.get("seat_id"),
                    "org_id": kwargs["org_id"],
                    "user_sub": kwargs["user_sub"],
                    "role": payload["role"],
                    "department_id": kwargs.get("department_id"),
                },
            )
        except Exception as e:
            logger.error("selva_office_seat_create failed: %s", e)
            return ToolResult(success=False, error=str(e))


class SelvaOfficeSeatAssignDepartmentTool(BaseTool):
    """Move an existing seat to a different department."""

    name = "selva_office_seat_assign_department"
    description = (
        "Re-assign an existing seat to a different department. The "
        "seat's current in-flight tasks carry to the new department "
        "(no task loss); only the zone + default-view changes. Safe to "
        "call repeatedly — the previous assignment is replaced."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seat_id": {"type": "string"},
                "department_id": {"type": "string"},
            },
            "required": ["seat_id", "department_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        sid = kwargs["seat_id"]
        try:
            status, body = await _request(
                "PATCH",
                f"/api/v1/office/seats/{sid}",
                json_body={"department_id": kwargs["department_id"]},
            )
            if not _ok(status):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=(f"Seat {sid} moved to department {kwargs['department_id']}"),
                data={
                    "seat_id": sid,
                    "department_id": kwargs["department_id"],
                },
            )
        except Exception as e:
            logger.error("selva_office_seat_assign_department failed: %s", e)
            return ToolResult(success=False, error=str(e))


class SelvaOfficeSeatRevokeTool(BaseTool):
    """Revoke a seat (offboard). HITL-gated."""

    name = "selva_office_seat_revoke"
    description = (
        "Revoke a seat. The user's access to the office UI stops "
        "immediately AND their in-flight tasks are re-queued for the "
        "team. HITL-gated — revoking a seat is part of offboarding and "
        "should go through a human sign-off since the user's audit trail "
        "remains but their perspective is permanently removed."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seat_id": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "Short reason — recorded in the audit log. "
                    "Examples: 'offboarded', 'role_change', 'contract_ended'.",
                },
            },
            "required": ["seat_id", "reason"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        sid = kwargs["seat_id"]
        try:
            status, body = await _request(
                "DELETE",
                f"/api/v1/office/seats/{sid}",
                json_body={"reason": kwargs["reason"]},
            )
            if not _ok(status):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=f"Seat {sid} revoked ({kwargs['reason']})",
                data={"seat_id": sid, "reason": kwargs["reason"]},
            )
        except Exception as e:
            logger.error("selva_office_seat_revoke failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_selva_office_provisioning_tools() -> list[BaseTool]:
    return [
        SelvaOfficeSeatCreateTool(),
        SelvaOfficeSeatAssignDepartmentTool(),
        SelvaOfficeSeatRevokeTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    SelvaOfficeSeatCreateTool,
    SelvaOfficeSeatAssignDepartmentTool,
    SelvaOfficeSeatRevokeTool,
):
    _cls.audience = Audience.PLATFORM
