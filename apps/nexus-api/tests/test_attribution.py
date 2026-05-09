"""Tests for T3.2 attribution closed-loop lead_id propagation.

Covers:
- `extract_lead_id` prefers explicit lead_id, falls through to deterministic hash.
- Hot-lead webhook preserves lead_id into the XADD SwarmTask payload.
- Webhook emits `lead.qualified` to PostHog with lead_id as distinct_id.
- Webhook does NOT use contact_email as distinct_id (would fork funnel).
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from nexus_api.attribution import (
    EVENT_LEAD_QUALIFIED,
    EVENT_PLAYBOOK_SENT,
    domain_of,
    emit_lead_qualified,
    extract_lead_id,
)

# ---------------------------------------------------------------------------
# extract_lead_id
# ---------------------------------------------------------------------------


class TestExtractLeadId:
    def test_prefers_explicit_lead_id(self) -> None:
        data = {"lead_id": "lead-abc-123", "id": "other", "contact_email": "x@y.com"}
        assert extract_lead_id(data) == "lead-abc-123"

    def test_falls_back_to_contact_id(self) -> None:
        data = {"id": "contact-xyz", "contact_email": "x@y.com"}
        assert extract_lead_id(data) == "contact-xyz"

    def test_deterministic_hash_when_no_explicit_id(self) -> None:
        data = {"contact_email": "user@example.com", "activity_id": "a-42"}
        expected_digest = hashlib.sha256(b"user@example.com|a-42").hexdigest()[:32]
        assert extract_lead_id(data) == f"lead_{expected_digest}"
        # Same input → same id (retry-safe)
        assert extract_lead_id(data) == extract_lead_id(dict(data))

    def test_empty_string_lead_id_falls_through(self) -> None:
        data = {"lead_id": "   ", "id": "contact-1"}
        assert extract_lead_id(data) == "contact-1"

    def test_last_resort_fresh_uuid_is_string(self) -> None:
        result = extract_lead_id({})
        assert isinstance(result, str)
        assert len(result) >= 32


# ---------------------------------------------------------------------------
# domain_of
# ---------------------------------------------------------------------------


class TestDomainOf:
    def test_domain_of_extracts_domain(self) -> None:
        assert domain_of("user@Example.com") == "example.com"

    def test_domain_of_returns_none_for_invalid(self) -> None:
        assert domain_of("not-an-email") is None
        assert domain_of("") is None
        assert domain_of(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# emit_lead_qualified  (PostHog integration)
# ---------------------------------------------------------------------------


class TestEmitLeadQualified:
    def test_uses_lead_id_as_distinct_id(self) -> None:
        """CRITICAL: lead_id must be distinct_id, never email."""
        captured: list[tuple] = []

        def _capture(distinct_id: str, event: str, properties: dict) -> None:
            captured.append((distinct_id, event, properties))

        with patch("nexus_api.attribution.track", side_effect=_capture):
            emit_lead_qualified(
                "lead-xyz",
                trigger_event="crm:hot_lead",
                playbook_name="Lead Response",
                task_id="task-1",
                extra={"recipient_domain": "example.com"},
            )

        assert len(captured) == 1
        distinct_id, event, properties = captured[0]
        assert distinct_id == "lead-xyz"  # NOT the email
        assert event == EVENT_LEAD_QUALIFIED
        assert properties["lead_id"] == "lead-xyz"
        assert properties["playbook"] == "Lead Response"
        assert properties["recipient_domain"] == "example.com"
        assert properties["utm_source"] == "selva"  # default

    def test_skips_when_lead_id_empty(self) -> None:
        with patch("nexus_api.attribution.track") as mock_track:
            emit_lead_qualified(
                "",
                trigger_event="x",
                playbook_name="y",
                task_id="z",
            )
            mock_track.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook threads lead_id into SwarmTask payload
# ---------------------------------------------------------------------------


class TestWebhookLeadIdPropagation:
    """Verify the CRM webhook preserves lead_id into the dispatched task."""

    async def test_explicit_lead_id_preserved_to_task_payload(
        self, client: httpx.AsyncClient
    ) -> None:
        mock_playbook = {
            "id": "pb-t32-1",
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

        captured_messages: list[dict] = []

        async def _capture_xadd(*args: object, **kwargs: object) -> None:
            if len(args) >= 3 and isinstance(args[2], dict):
                captured_messages.append(json.loads(args[2]["data"]))

        mock_redis_pool = MagicMock()
        mock_redis_pool.execute_with_retry = AsyncMock(side_effect=_capture_xadd)

        with (
            patch(
                "nexus_api.routers.playbooks._playbooks",
                {"pb-t32-1": mock_playbook},
            ),
            patch(
                "selva_redis_pool.get_redis_pool",
                return_value=mock_redis_pool,
            ),
            patch("nexus_api.attribution.track") as mock_track,
        ):
            payload = {
                "event": "lead.hot",
                "data": {
                    "lead_id": "lead-t32-abc",
                    "contact_name": "Lupita",
                    "contact_email": "lupita@acme.mx",
                    "utm_source": "selva",
                },
            }
            resp = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "dispatched"
            assert body["lead_id"] == "lead-t32-abc"

            # SwarmTask payload preserves lead_id
            assert len(captured_messages) == 1
            msg = captured_messages[0]
            assert msg["lead_id"] == "lead-t32-abc"
            assert msg["payload"]["lead_id"] == "lead-t32-abc"
            assert msg["payload"]["utm_source"] == "selva"
            assert msg["payload"]["utm_campaign"] == "hot_lead_auto"

            # PostHog lead.qualified fired with lead_id as distinct_id
            mock_track.assert_called_once()
            distinct_id, event_name, props = mock_track.call_args[0]
            assert distinct_id == "lead-t32-abc"
            assert event_name == EVENT_LEAD_QUALIFIED
            assert props["lead_id"] == "lead-t32-abc"
            assert props["playbook"] == "Lead Response"
            assert props["recipient_domain"] == "acme.mx"

    async def test_missing_lead_id_derives_deterministic_fallback(
        self, client: httpx.AsyncClient
    ) -> None:
        """Webhook retries with same contact+activity must produce same lead_id."""
        mock_playbook = {
            "id": "pb-t32-2",
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

        async def _capture_xadd(*args: object, **kwargs: object) -> None:
            if len(args) >= 3 and isinstance(args[2], dict):
                captured_messages.append(json.loads(args[2]["data"]))

        mock_redis_pool = MagicMock()
        mock_redis_pool.execute_with_retry = AsyncMock(side_effect=_capture_xadd)

        payload = {
            "event": "lead.hot",
            "data": {
                # No explicit lead_id — rely on fallback hash
                "contact_email": "det@example.com",
                "activity_id": "act-777",
            },
        }

        with (
            patch(
                "nexus_api.routers.playbooks._playbooks",
                {"pb-t32-2": mock_playbook},
            ),
            patch(
                "selva_redis_pool.get_redis_pool",
                return_value=mock_redis_pool,
            ),
            patch("nexus_api.attribution.track"),
        ):
            resp1 = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp2 = await client.post(
                "/api/v1/gateway/phynd-crm",
                content=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp1.status_code == 200
            assert resp2.status_code == 200
            # Same inputs → same lead_id (retry-safe attribution)
            assert resp1.json()["lead_id"] == resp2.json()["lead_id"]
            assert resp1.json()["lead_id"].startswith("lead_")
            assert len(captured_messages) == 2
            assert captured_messages[0]["lead_id"] == captured_messages[1]["lead_id"]


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_event_name_constants_match_contract() -> None:
    """Event names must match the attribution contract exactly."""
    assert EVENT_LEAD_QUALIFIED == "lead.qualified"
    assert EVENT_PLAYBOOK_SENT == "playbook.sent"
