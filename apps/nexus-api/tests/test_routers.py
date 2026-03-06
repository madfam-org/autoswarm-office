"""Comprehensive tests for nexus-api routers.

Covers the health, billing, and approvals endpoints using an in-memory SQLite
database (configured in conftest.py) so no external services are required.

Test categories
---------------
- Health endpoints: liveness probe
- Billing endpoints: status, usage, token status
- Approval endpoints: create, list pending, approve, deny, get by ID, edge cases
"""

from __future__ import annotations

import uuid

import httpx
import pytest


# =============================================================================
# Health router
# =============================================================================


class TestHealthRouter:
    """Tests for GET /api/v1/health/health."""

    async def test_health_endpoint(self, client: httpx.AsyncClient) -> None:
        """Health probe returns 200 with service metadata."""
        resp = await client.get("/api/v1/health/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["service"] == "nexus-api"
        assert "version" in body

    async def test_health_no_auth_required(self, client: httpx.AsyncClient) -> None:
        """Health endpoint does not require authentication."""
        resp = await client.get("/api/v1/health/health")
        assert resp.status_code == 200


# =============================================================================
# Billing router
# =============================================================================


class TestBillingRouter:
    """Tests for the /api/v1/billing/* endpoints.

    All billing endpoints require authentication (router-level dependency).
    """

    # -- GET /api/v1/billing/status -------------------------------------------

    async def test_billing_status(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Billing status returns a dict containing the subscription tier."""
        resp = await client.get("/api/v1/billing/status", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "tier" in body

    async def test_billing_status_requires_auth(self, client: httpx.AsyncClient) -> None:
        """Billing status returns 401 without a Bearer token."""
        resp = await client.get("/api/v1/billing/status")
        assert resp.status_code in (401, 403)

    # -- GET /api/v1/billing/usage --------------------------------------------

    async def test_billing_usage(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Usage endpoint returns today's date and aggregated token usage."""
        resp = await client.get("/api/v1/billing/usage", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "date" in body
        assert "total_used" in body
        assert "by_action" in body
        assert body["total_used"] == 0  # no ledger entries yet

    async def test_billing_usage_requires_auth(self, client: httpx.AsyncClient) -> None:
        """Usage endpoint returns 401 without a Bearer token."""
        resp = await client.get("/api/v1/billing/usage")
        assert resp.status_code in (401, 403)

    # -- GET /api/v1/billing/tokens -------------------------------------------

    async def test_billing_tokens(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Token status returns daily limit, used count, and remaining."""
        resp = await client.get("/api/v1/billing/tokens", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "daily_limit" in body
        assert body["daily_limit"] == 1000
        assert body["used"] == 0
        assert body["remaining"] == 1000
        assert "reset_at" in body

    async def test_billing_tokens_requires_auth(self, client: httpx.AsyncClient) -> None:
        """Token status returns 401 without a Bearer token."""
        resp = await client.get("/api/v1/billing/tokens")
        assert resp.status_code in (401, 403)


# =============================================================================
# Approvals router
# =============================================================================


class TestCreateApproval:
    """Tests for POST /api/v1/approvals/ (create approval request)."""

    async def test_create_approval_request(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Creating an approval request returns 201 with a pending status."""
        payload = {
            "agent_id": sample_agent_id,
            "action_category": "code_execution",
            "action_type": "run_script",
            "payload": {"script": "deploy.py"},
            "reasoning": "Automated deployment needs approval",
            "urgency": "high",
        }

        resp = await client.post("/api/v1/approvals/", json=payload, headers=auth_headers)

        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["agent_id"] == sample_agent_id
        assert body["action_category"] == "code_execution"
        assert body["action_type"] == "run_script"
        assert body["urgency"] == "high"
        assert body["reasoning"] == "Automated deployment needs approval"
        assert body["feedback"] is None
        assert body["responded_at"] is None
        # Verify the id is a valid UUID.
        uuid.UUID(body["id"])

    async def test_create_approval_no_auth_required(
        self, client: httpx.AsyncClient, sample_agent_id: str
    ) -> None:
        """The create endpoint does not require authentication (called by workers)."""
        payload = {
            "agent_id": sample_agent_id,
            "action_category": "file_write",
            "action_type": "overwrite",
        }
        resp = await client.post("/api/v1/approvals/", json=payload)
        assert resp.status_code == 201

    async def test_create_approval_default_values(
        self, client: httpx.AsyncClient, sample_agent_id: str
    ) -> None:
        """Omitted optional fields receive their defaults."""
        payload = {
            "agent_id": sample_agent_id,
            "action_category": "shell",
            "action_type": "exec",
        }
        resp = await client.post("/api/v1/approvals/", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["urgency"] == "medium"
        assert body["reasoning"] == ""
        assert body["payload"] == {}
        assert body["diff"] is None

    async def test_create_approval_invalid_agent_id(
        self, client: httpx.AsyncClient
    ) -> None:
        """An invalid agent_id UUID returns 400."""
        payload = {
            "agent_id": "not-a-uuid",
            "action_category": "code_execution",
            "action_type": "run",
        }
        resp = await client.post("/api/v1/approvals/", json=payload)
        assert resp.status_code == 400

    async def test_create_approval_invalid_urgency(
        self, client: httpx.AsyncClient, sample_agent_id: str
    ) -> None:
        """An invalid urgency value is rejected by pydantic validation (422)."""
        payload = {
            "agent_id": sample_agent_id,
            "action_category": "code_execution",
            "action_type": "run",
            "urgency": "super-urgent",  # not in the pattern
        }
        resp = await client.post("/api/v1/approvals/", json=payload)
        assert resp.status_code == 422

    async def test_create_approval_missing_required_fields(
        self, client: httpx.AsyncClient
    ) -> None:
        """Omitting required fields returns 422."""
        resp = await client.post("/api/v1/approvals/", json={})
        assert resp.status_code == 422


class TestListApprovals:
    """Tests for GET /api/v1/approvals/ (list pending approvals)."""

    async def test_list_approvals_empty(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Returns an empty list when no approvals exist."""
        resp = await client.get("/api/v1/approvals/", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_approvals_pending(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Returns only pending approval requests."""
        # Create two approval requests.
        for action_type in ("run_script", "write_file"):
            await client.post(
                "/api/v1/approvals/",
                json={
                    "agent_id": sample_agent_id,
                    "action_category": "code_execution",
                    "action_type": action_type,
                },
            )

        resp = await client.get("/api/v1/approvals/", headers=auth_headers)

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        assert all(item["status"] == "pending" for item in items)

    async def test_list_approvals_excludes_resolved(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Resolved approvals do not appear in the pending list."""
        # Create and approve one request.
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run_script",
            },
        )
        approval_id = create_resp.json()["id"]
        await client.post(
            f"/api/v1/approvals/{approval_id}/approve", headers=auth_headers
        )

        # The pending list should be empty now.
        resp = await client.get("/api/v1/approvals/", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_approvals_requires_auth(
        self, client: httpx.AsyncClient
    ) -> None:
        """Listing pending approvals requires authentication."""
        resp = await client.get("/api/v1/approvals/")
        assert resp.status_code in (401, 403)


class TestGetApproval:
    """Tests for GET /api/v1/approvals/{request_id}."""

    async def test_get_approval_by_id(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Fetching a single approval by ID returns its full details."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "database",
                "action_type": "migration",
                "reasoning": "Schema update required",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/approvals/{approval_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == approval_id
        assert body["action_category"] == "database"
        assert body["reasoning"] == "Schema update required"

    async def test_get_approval_not_found(self, client: httpx.AsyncClient) -> None:
        """Requesting a non-existent approval returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/approvals/{fake_id}")
        assert resp.status_code == 404

    async def test_get_approval_invalid_uuid(self, client: httpx.AsyncClient) -> None:
        """Requesting with an invalid UUID returns 400."""
        resp = await client.get("/api/v1/approvals/not-a-uuid")
        assert resp.status_code == 400


class TestApproveRequest:
    """Tests for POST /api/v1/approvals/{request_id}/approve."""

    async def test_approve_request(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Approving a pending request sets status to 'approved'."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run_script",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"feedback": "Looks good, proceed."},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["feedback"] == "Looks good, proceed."
        assert body["responded_at"] is not None

    async def test_approve_request_no_feedback(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Approving without a body (no feedback) still succeeds."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["feedback"] is None

    async def test_approve_already_approved(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Approving an already-resolved request returns 409 Conflict."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]

        # First approval succeeds.
        await client.post(
            f"/api/v1/approvals/{approval_id}/approve", headers=auth_headers
        )

        # Second approval returns conflict.
        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/approve", headers=auth_headers
        )
        assert resp.status_code == 409

    async def test_approve_nonexistent_request(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Approving a non-existent request returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/approvals/{fake_id}/approve", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_approve_requires_auth(
        self,
        client: httpx.AsyncClient,
        sample_agent_id: str,
    ) -> None:
        """Approving a request requires authentication."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/approvals/{approval_id}/approve")
        assert resp.status_code in (401, 403)


class TestDenyRequest:
    """Tests for POST /api/v1/approvals/{request_id}/deny."""

    async def test_deny_request(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Denying a pending request sets status to 'denied'."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run_script",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/deny",
            json={"feedback": "Too risky, please revise."},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "denied"
        assert body["feedback"] == "Too risky, please revise."
        assert body["responded_at"] is not None

    async def test_deny_already_denied(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Denying an already-resolved request returns 409 Conflict."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]
        await client.post(
            f"/api/v1/approvals/{approval_id}/deny", headers=auth_headers
        )

        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/deny", headers=auth_headers
        )
        assert resp.status_code == 409

    async def test_deny_requires_auth(
        self,
        client: httpx.AsyncClient,
        sample_agent_id: str,
    ) -> None:
        """Denying a request requires authentication."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/approvals/{approval_id}/deny")
        assert resp.status_code in (401, 403)

    async def test_approve_after_deny_conflict(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_agent_id: str,
    ) -> None:
        """Approving a previously denied request returns 409."""
        create_resp = await client.post(
            "/api/v1/approvals/",
            json={
                "agent_id": sample_agent_id,
                "action_category": "code_execution",
                "action_type": "run",
            },
        )
        approval_id = create_resp.json()["id"]
        await client.post(
            f"/api/v1/approvals/{approval_id}/deny", headers=auth_headers
        )

        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/approve", headers=auth_headers
        )
        assert resp.status_code == 409
