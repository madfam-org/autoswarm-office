"""Regression tests for the approvals POST service-role gate (commit f35f1b1).

Pre-fix: ``POST /api/v1/approvals`` accepted any authenticated caller and
read ``org_id`` from the request body. A logged-in tactician (or any
JWT-bearing user) could create approval requests targeting an arbitrary
agent or tenant.

Post-fix: the route requires the caller to have ``service`` or ``worker``
role; the body schema dropped the ``org_id`` field; the persisted
``org_id`` is derived from the authenticated caller.

These tests pin both the role gate and the org-derivation behaviour.
"""

from __future__ import annotations

import inspect
import uuid

import httpx
import pytest

from nexus_api.auth import get_current_user
from nexus_api.main import app as _fastapi_app
from nexus_api.routers.approvals import (
    create_approval_request,
    get_approval_request,
    list_pending_approvals,
)


def _service_user(org_id: str = "dev-org") -> dict:
    return {
        "sub": "service:test-worker",
        "roles": ["service", "worker"],
        "org_id": org_id,
        "email": "worker@selva.internal",
    }


def _regular_user(org_id: str = "dev-org") -> dict:
    """A normal authenticated tactician, NO service/worker role."""
    return {
        "sub": "user-00000001",
        "roles": ["admin", "tactician"],
        "org_id": org_id,
        "email": "user@example.com",
    }


def _approval_payload(agent_id: str | None = None) -> dict:
    return {
        "agent_id": agent_id or str(uuid.uuid4()),
        "action_category": "code_modification",
        "action_type": "test_action",
        "payload": {"file": "/tmp/test"},
        "reasoning": "test reasoning",
        "urgency": "medium",
    }


def _param_index(callable_obj: object, name: str) -> int:
    return list(inspect.signature(callable_obj).parameters).index(name)


def test_approval_routes_resolve_tenant_before_db_session() -> None:
    """RLS needs auth/tenant context set before ``get_db`` opens a session."""
    assert _param_index(create_approval_request, "user") < _param_index(
        create_approval_request, "db"
    )
    assert _param_index(list_pending_approvals, "tenant") < _param_index(
        list_pending_approvals, "db"
    )
    assert _param_index(get_approval_request, "tenant") < _param_index(
        get_approval_request, "db"
    )


@pytest.mark.asyncio
class TestCreateApprovalRequestRoleGate:
    """Only callers with service/worker role may POST /approvals."""

    async def test_create_approval_request_requires_service_role(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A regular tactician (no service role) gets 403.

        We override get_current_user to return a tactician user (no
        service/worker role) and confirm the route returns 403, not
        201. Without this guard a JWT-bearing user could spoof
        worker-style approval-request creation.
        """
        try:
            _fastapi_app.dependency_overrides[get_current_user] = lambda: _regular_user()

            resp = await client.post(
                "/api/v1/approvals/",
                json=_approval_payload(),
                headers=auth_headers,
            )
            assert resp.status_code == 403
            detail = resp.json().get("detail", "").lower()
            assert "service" in detail or "worker" in detail
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    async def test_create_approval_request_allows_service_role(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A worker with service role can create the request (control case)."""
        try:
            _fastapi_app.dependency_overrides[get_current_user] = lambda: _service_user()

            resp = await client.post(
                "/api/v1/approvals/",
                json=_approval_payload(),
                headers=auth_headers,
            )
            # 201 expected; if the dependency wiring breaks anywhere
            # downstream we want a clear failure here, not a silent 403.
            assert resp.status_code == 201, (
                f"Service role POST should succeed; got {resp.status_code}: {resp.text}"
            )

            body = resp.json()
            assert body["status"] == "pending"
            assert body["action_category"] == "code_modification"
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    async def test_create_approval_request_ignores_body_org_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Body-injected ``org_id`` MUST NOT influence the persisted row.

        Pre-fix the body's org_id field was honoured, so a worker could
        create approval requests in any tenant. Post-fix the field is
        not on the schema (Pydantic 2 drops unknown fields silently)
        and the persisted org_id comes from the authenticated caller.
        """
        try:
            # Override to a service user attributed to org-A.
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _service_user(org_id="caller-tenant-A")
            )

            payload = _approval_payload()
            payload["org_id"] = "victim-tenant-B"  # hostile field

            resp = await client.post(
                "/api/v1/approvals/",
                json=payload,
                headers=auth_headers,
            )
            assert resp.status_code == 201

            # We can't read the org_id back from the response model
            # (it's not exposed there), but reading the row via the
            # GET endpoint as the same caller must succeed (proving
            # it lives in caller-tenant-A, not victim-tenant-B).
            req_id = resp.json()["id"]
            get_resp = await client.get(
                f"/api/v1/approvals/{req_id}",
                headers=auth_headers,
            )
            assert get_resp.status_code == 200, (
                "Approval should be visible to the caller's tenant."
            )
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)
