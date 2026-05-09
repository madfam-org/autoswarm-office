"""Tests for the PhyndCRM webhook handler.

Covers:
- HMAC signature verification
- CRM event → internal event mapping
- Playbook matching and auto-dispatch flow
- Unknown event types are acknowledged but ignored
- Invalid JSON handling
- Signature verification failure
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign_payload(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _make_crm_event(event: str, data: dict | None = None) -> dict:
    """Build a PhyndCRM webhook event payload."""
    return {
        "event": event,
        "data": data or {},
    }


# ---------------------------------------------------------------------------
# Event mapping
# ---------------------------------------------------------------------------


class TestCRMEventMapping:
    """Verify CRM events are correctly mapped to internal events."""

    async def test_known_event_acknowledged(self, client: httpx.AsyncClient) -> None:
        """A known CRM event with no matching playbook returns ok + no_playbook."""
        # Clear playbooks so no match occurs
        with patch(
            "nexus_api.routers.playbooks._playbooks",
            {},
        ):
            payload = _make_crm_event("lead.hot", {"contact_name": "Test", "email": "t@t.com"})
            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data.get("no_playbook") is True

    async def test_unknown_event_ignored(self, client: httpx.AsyncClient) -> None:
        """An unknown CRM event type is acknowledged but marked as ignored."""
        payload = _make_crm_event("unknown.event", {"foo": "bar"})
        resp = await client.post(
            "/api/v1/gateway/phynd-crm",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data.get("ignored") is True

    async def test_empty_event_ignored(self, client: httpx.AsyncClient) -> None:
        payload = {"event": "", "data": {}}
        resp = await client.post(
            "/api/v1/gateway/phynd-crm",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ignored") is True


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class TestCRMWebhookSignature:
    """Verify HMAC-SHA256 signature enforcement."""

    async def test_invalid_signature_rejected(self, client: httpx.AsyncClient) -> None:
        """When a webhook secret is configured, invalid signatures are rejected."""
        payload = json.dumps(_make_crm_event("lead.hot")).encode()

        with patch(
            "nexus_api.routers.crm_webhooks.get_settings",
        ) as mock_settings:
            settings_obj = MagicMock()
            settings_obj.phyne_crm_webhook_secret = "test-secret-123"
            settings_obj.redis_url = "redis://localhost:6379"
            mock_settings.return_value = settings_obj

            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-PhyndCRM-Signature": "invalid-signature",
                },
            )
            assert resp.status_code == 401

    async def test_valid_signature_accepted(self, client: httpx.AsyncClient) -> None:
        """A correctly signed payload passes verification."""
        payload = json.dumps(_make_crm_event("unknown.event")).encode()
        secret = "test-secret-456"
        signature = _sign_payload(payload, secret)

        with patch(
            "nexus_api.routers.crm_webhooks.get_settings",
        ) as mock_settings:
            settings_obj = MagicMock()
            settings_obj.phyne_crm_webhook_secret = secret
            settings_obj.redis_url = "redis://localhost:6379"
            mock_settings.return_value = settings_obj

            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-PhyndCRM-Signature": signature,
                },
            )
            assert resp.status_code == 200

    async def test_no_secret_configured_skips_verification(self, client: httpx.AsyncClient) -> None:
        """When no webhook secret is configured, signature check is skipped."""
        payload = _make_crm_event("unknown.event")
        resp = await client.post(
            "/api/v1/gateway/phynd-crm",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


class TestCRMWebhookValidation:
    """Input validation edge cases."""

    async def test_invalid_json_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/gateway/phynd-crm",
            content=b"not valid json{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_missing_event_field_ignored(self, client: httpx.AsyncClient) -> None:
        """A payload without an 'event' key is treated as unknown and ignored."""
        resp = await client.post(
            "/api/v1/gateway/phynd-crm",
            content=json.dumps({"data": {}}).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ignored") is True


# ---------------------------------------------------------------------------
# Auto-dispatch flow
# ---------------------------------------------------------------------------


class TestCRMAutoDispatch:
    """Verify auto-dispatch creates a task when a matching playbook exists."""

    async def test_dispatch_on_matching_playbook(self, client: httpx.AsyncClient) -> None:
        """lead.hot event with a matching 'Lead Response' playbook dispatches a task."""
        mock_playbook = {
            "id": "pb-test-001",
            "name": "Lead Response",
            "trigger_event": "crm:hot_lead",
            "allowed_actions": ["api_call", "email_send"],
            "token_budget": 50,
            "financial_cap_cents": 0,
            "require_approval": False,
            "enabled": True,
            "org_id": "test",
            "created_at": "2026-01-01T00:00:00Z",
        }

        mock_redis_pool = MagicMock()
        mock_redis_pool.execute_with_retry = AsyncMock()

        with (
            patch(
                "nexus_api.routers.playbooks._playbooks",
                {"pb-test-001": mock_playbook},
            ),
            patch(
                "selva_redis_pool.get_redis_pool",
                return_value=mock_redis_pool,
            ),
        ):
            payload = _make_crm_event(
                "lead.hot",
                {
                    "contact_name": "Juan Garcia",
                    "contact_email": "juan@example.com",
                },
            )
            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "dispatched"
            assert data["playbook"] == "Lead Response"
            assert data["graph_type"] == "crm"
            assert "task_id" in data

            # Verify Redis XADD was called
            mock_redis_pool.execute_with_retry.assert_awaited_once()
            call_args = mock_redis_pool.execute_with_retry.call_args
            assert call_args[0][0] == "xadd"
            assert call_args[0][1] == "autoswarm:task-stream"

    async def test_dispatch_includes_crm_data_in_task(self, client: httpx.AsyncClient) -> None:
        """The dispatched task message includes CRM event data for the agent."""
        mock_playbook = {
            "id": "pb-test-002",
            "name": "Lead Response",
            "trigger_event": "crm:hot_lead",
            "allowed_actions": ["api_call"],
            "token_budget": 50,
            "financial_cap_cents": 0,
            "require_approval": False,
            "enabled": True,
            "org_id": "test",
            "created_at": "2026-01-01T00:00:00Z",
        }

        captured_messages: list[dict] = []

        async def capture_xadd(*args: object, **kwargs: object) -> None:
            if len(args) >= 3 and isinstance(args[2], dict):
                captured_messages.append(json.loads(args[2]["data"]))

        mock_redis_pool = MagicMock()
        mock_redis_pool.execute_with_retry = AsyncMock(side_effect=capture_xadd)

        with (
            patch(
                "nexus_api.routers.playbooks._playbooks",
                {"pb-test-002": mock_playbook},
            ),
            patch(
                "selva_redis_pool.get_redis_pool",
                return_value=mock_redis_pool,
            ),
        ):
            payload = _make_crm_event(
                "lead.hot",
                {
                    "contact_name": "Maria",
                    "contact_email": "maria@test.com",
                    "company": "Acme Corp",
                },
            )
            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200

            assert len(captured_messages) == 1
            msg = captured_messages[0]
            assert msg["graph_type"] == "crm"
            assert msg["playbook_id"] == "pb-test-002"
            assert msg["payload"]["crm_data"]["contact_name"] == "Maria"

    async def test_graph_type_mapping(self, client: httpx.AsyncClient) -> None:
        """Different CRM events map to the correct graph types."""
        mock_playbook = {
            "id": "pb-support-001",
            "name": "Support",
            "trigger_event": "crm:support_ticket",
            "allowed_actions": ["api_call"],
            "token_budget": 50,
            "financial_cap_cents": 0,
            "require_approval": False,
            "enabled": True,
            "org_id": "test",
            "created_at": "2026-01-01T00:00:00Z",
        }

        mock_redis_pool = MagicMock()
        mock_redis_pool.execute_with_retry = AsyncMock()

        with (
            patch(
                "nexus_api.routers.playbooks._playbooks",
                {"pb-support-001": mock_playbook},
            ),
            patch(
                "selva_redis_pool.get_redis_pool",
                return_value=mock_redis_pool,
            ),
        ):
            payload = _make_crm_event("activity.overdue", {"id": "act-1"})
            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            assert resp.json()["graph_type"] == "support"
