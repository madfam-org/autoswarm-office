"""Tests for Dhanam-first billing sync (canonical Stripe/POS router).

These tests PIN Dhanam's real outbound product-webhook envelope, verified
against Dhanam source on 2026-07-28:

- Subscription envelope builder:
  ``dhanam/apps/api/src/modules/billing/services/subscription-janua-notifier.service.ts:137-148``
  → ``{type, id, data: {customer_id, subscription_id, plan_id,
  organization_id, status}, timestamp}`` — ``data.plan_id`` (e.g.
  ``selva_team``) and ``data.organization_id``, NOT the ``data.tier`` /
  ``data.org_id`` this reader historically expected. That drift meant a
  completed Selva purchase never applied the tier upgrade.
- Dispatch trigger for a Selva purchase (Stripe federation path):
  ``dhanam/apps/api/src/modules/billing/services/webhook-processor.service.ts:781-789``
  with org attribution propagated from checkout ``metadata.orgId``
  (``webhook-processor.service.ts:188``).
- Payment fan-out envelope (relayed to ALL consumers, no organization_id):
  ``dhanam/apps/api/src/modules/billing/services/stripe-mx-spei-relay.service.ts:138-194``.
- Signature: HMAC-SHA256 hex of the raw body under the shared webhook
  secret, ``X-Dhanam-Signature`` header
  (``subscription-janua-notifier.service.ts:150,161``).

The field names in the fixtures below are the contract. If Dhanam renames a
field these tests are the tripwire — do not "fix" a failure here by editing
the fixture without re-verifying Dhanam's envelope builder.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from nexus_api.models import TenantConfig
from nexus_api.services.billing_sync import (
    UnrecognizedDhanamEnvelopeError,
    handle_dhanam_billing_event,
)

_SYNC_LOGGER = "nexus_api.services.billing_sync"


def _canonical_subscription_envelope(
    *,
    event_type: str = "subscription.created",
    plan_id: str = "selva_team",
    organization_id: str = "org-dhanam-1",
    subscription_id: str | None = "sub_test_123",
) -> dict[str, object]:
    """Envelope exactly as Dhanam's ``notifyProductWebhooks`` builds it
    (subscription-janua-notifier.service.ts:137-148). ``data.status`` is the
    event-type suffix, not a lifecycle status — also part of the contract."""
    data: dict[str, object] = {
        "customer_id": "dhanam-user-uuid-1",
        "plan_id": plan_id,
        "organization_id": organization_id,
        "status": event_type.split(".")[1] if "." in event_type else "created",
    }
    if subscription_id is not None:
        data["subscription_id"] = subscription_id
    return {
        "type": event_type,
        "id": "11111111-2222-3333-4444-555555555555",
        "data": data,
        "timestamp": "2026-07-28T12:00:00.000Z",
    }


async def _seed_tenant(db_session, org_id: str = "org-dhanam-1") -> None:
    db_session.add(
        TenantConfig(
            org_id=org_id,
            brand_name="Test",
            subscription_tier="starter",
            subscription_status="active",
        )
    )
    await db_session.commit()


async def _get_tenant(db_session, org_id: str = "org-dhanam-1") -> TenantConfig:
    result = await db_session.execute(
        select(TenantConfig).where(TenantConfig.org_id == org_id)
    )
    return result.scalar_one()


class TestCanonicalEnvelope:
    """The dhanam→selva contract: canonical field names apply state."""

    @pytest.mark.asyncio
    async def test_subscription_created_applies_tier_upgrade(self, db_session) -> None:
        """A completed Selva purchase (plan selva_team) upgrades the tenant.

        This is the drift regression test: the envelope carries plan_id +
        organization_id, and the reader must apply tier `professional`
        (catalog tier `team` mapped into the pricing vocabulary)."""
        await _seed_tenant(db_session)

        payload = _canonical_subscription_envelope()
        with patch(
            "nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()
        ) as mock_cache:
            await handle_dhanam_billing_event(payload)

        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "professional"
        # Envelope status "created" is an event suffix; projected to active.
        assert tenant.subscription_status == "active"
        # Canonical subscription_id is the upstream subscription reference.
        assert tenant.stripe_subscription_id == "sub_test_123"
        # data.customer_id is a Dhanam-side id, NOT a Stripe customer id —
        # it must never be written into stripe_customer_id.
        assert tenant.stripe_customer_id is None
        mock_cache.assert_awaited_once_with("org-dhanam-1", "professional")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("plan_id", "expected_tier"),
        [
            ("selva_developer", "starter"),
            ("selva_team", "professional"),
            ("selva_business", "enterprise"),
            # Already-canonical slugs pass through without double translation.
            ("selva_starter", "starter"),
        ],
    )
    async def test_catalog_plan_ids_map_to_pricing_tiers(
        self, db_session, plan_id: str, expected_tier: str
    ) -> None:
        await _seed_tenant(db_session)
        payload = _canonical_subscription_envelope(plan_id=plan_id)
        with patch("nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == expected_tier

    @pytest.mark.asyncio
    async def test_subscription_updated_applies(self, db_session) -> None:
        await _seed_tenant(db_session)
        payload = _canonical_subscription_envelope(
            event_type="subscription.updated", plan_id="selva_business"
        )
        with patch("nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "enterprise"
        assert tenant.subscription_status == "active"

    @pytest.mark.asyncio
    async def test_subscription_cancelled_marks_cancelled(self, db_session) -> None:
        """Cancel events resolve the org via the canonical field too.

        Note: Dhanam's dispatcher currently never emits cancels to product
        webhooks (empty plan id is dropped at
        subscription-janua-notifier.service.ts:121-122); this pins the reader
        for when that upstream gap is fixed."""
        await _seed_tenant(db_session)
        payload = {
            "type": "subscription.cancelled",
            "id": "66666666-7777-8888-9999-000000000000",
            "data": {
                "customer_id": "dhanam-user-uuid-1",
                "plan_id": "selva_team",
                "organization_id": "org-dhanam-1",
                "status": "cancelled",
            },
            "timestamp": "2026-07-28T12:00:00.000Z",
        }
        await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_status == "cancelled"

    @pytest.mark.asyncio
    async def test_unknown_catalog_tier_applied_loudly(self, db_session, caplog) -> None:
        """A novel catalog tier (no configured daily limit) still records the
        truth, with a counted warning instead of a silent default."""
        await _seed_tenant(db_session)
        payload = _canonical_subscription_envelope(plan_id="selva_scale")
        with (
            patch(
                "nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()
            ) as mock_cache,
            caplog.at_level(logging.WARNING, logger=_SYNC_LOGGER),
        ):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "scale"
        mock_cache.assert_awaited_once_with("org-dhanam-1", "scale")
        assert "dhanam_envelope_unknown_tier" in caplog.text


class TestOrgResolution:
    """org attribution: organization_id first, tolerated fallbacks are loud."""

    @pytest.mark.asyncio
    async def test_legacy_org_id_and_tier_fields_still_apply_with_warning(
        self, db_session, caplog
    ) -> None:
        """The pre-fix imagined shape (org_id/tier) keeps working, loudly.

        Also pins that the legacy external_customer_id / dhanam_space_id
        passthroughs stay intact."""
        await _seed_tenant(db_session)
        payload = {
            "type": "subscription.updated",
            "data": {
                "org_id": "org-dhanam-1",
                "tier": "professional",
                "status": "active",
                "dhanam_space_id": "space-abc",
                "external_customer_id": "cus_dhanam_1",
            },
        }
        with (
            patch(
                "nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()
            ) as mock_cache,
            caplog.at_level(logging.WARNING, logger=_SYNC_LOGGER),
        ):
            await handle_dhanam_billing_event(payload)

        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "professional"
        assert tenant.stripe_customer_id == "cus_dhanam_1"
        assert tenant.dhanam_space_id == "space-abc"
        mock_cache.assert_awaited_once_with("org-dhanam-1", "professional")
        assert "dhanam_envelope_legacy_field" in caplog.text

    @pytest.mark.asyncio
    async def test_metadata_orgid_fallback_resolves_org(self, db_session, caplog) -> None:
        """#257's checkout stamps metadata.orgId; Dhanam propagates it into
        organization_id, but a nested metadata.orgId is accepted (loudly) as
        a defensive last resort."""
        await _seed_tenant(db_session)
        payload = {
            "type": "subscription.created",
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "data": {
                "customer_id": "dhanam-user-uuid-1",
                "plan_id": "selva_team",
                "status": "created",
                "metadata": {"orgId": "org-dhanam-1"},
            },
            "timestamp": "2026-07-28T12:00:00.000Z",
        }
        with (
            patch("nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()),
            caplog.at_level(logging.WARNING, logger=_SYNC_LOGGER),
        ):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "professional"
        assert "dhanam_envelope_metadata_org_fallback" in caplog.text


class TestUnrecognizedEnvelopes:
    """Parses-but-matches-nothing must be a counted error, never silent 200."""

    @pytest.mark.asyncio
    async def test_unknown_event_type_raises(self, caplog) -> None:
        payload = {
            "type": "subscription.paused",
            "id": "12121212-3434-5656-7878-909090909090",
            "data": {"customer_id": "dhanam-user-uuid-1"},
            "timestamp": "2026-07-28T12:00:00.000Z",
        }
        with (
            caplog.at_level(logging.ERROR, logger=_SYNC_LOGGER),
            pytest.raises(UnrecognizedDhanamEnvelopeError) as excinfo,
        ):
            await handle_dhanam_billing_event(payload)
        assert excinfo.value.reason == "unknown_event_type"
        assert "dhanam_envelope_unrecognized" in caplog.text

    @pytest.mark.asyncio
    async def test_missing_org_raises(self, caplog) -> None:
        """Pins the real upstream gap: Dhanam's Janua-path subscription.updated
        dispatches with an empty organization_id
        (webhook-processor.service.ts:926 passes '' as orgId). A Selva plan
        with no org is unapplyable and must be rejected loudly."""
        payload = _canonical_subscription_envelope(
            event_type="subscription.updated", organization_id=""
        )
        with (
            caplog.at_level(logging.ERROR, logger=_SYNC_LOGGER),
            pytest.raises(UnrecognizedDhanamEnvelopeError) as excinfo,
        ):
            await handle_dhanam_billing_event(payload)
        assert excinfo.value.reason == "missing_org"
        assert "dhanam_envelope_unrecognized" in caplog.text

    @pytest.mark.asyncio
    async def test_missing_tier_raises(self, caplog) -> None:
        payload = {
            "type": "subscription.created",
            "id": "99999999-8888-7777-6666-555555555555",
            "data": {
                "customer_id": "dhanam-user-uuid-1",
                "organization_id": "org-dhanam-1",
                "status": "created",
            },
            "timestamp": "2026-07-28T12:00:00.000Z",
        }
        with (
            caplog.at_level(logging.ERROR, logger=_SYNC_LOGGER),
            pytest.raises(UnrecognizedDhanamEnvelopeError) as excinfo,
        ):
            await handle_dhanam_billing_event(payload)
        assert excinfo.value.reason == "missing_tier"


class TestToleratedTraffic:
    """Known-shape traffic that is deliberately not applied stays 2xx, loudly."""

    @pytest.mark.asyncio
    async def test_foreign_plan_acknowledged_not_applied(self, db_session, caplog) -> None:
        """Another product's plan reaching this endpoint is acknowledged with
        a counted warning — never applied, never a retryable error."""
        await _seed_tenant(db_session)
        payload = _canonical_subscription_envelope(plan_id="janua_pro")
        with caplog.at_level(logging.WARNING, logger=_SYNC_LOGGER):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "starter"  # unchanged
        assert "dhanam_envelope_foreign_plan" in caplog.text

    @pytest.mark.asyncio
    async def test_payment_fanout_event_acknowledged(self, db_session, caplog) -> None:
        """payment.* envelopes fan out to every consumer and carry no
        organization_id (stripe-mx-spei-relay.service.ts:138-194; fan-out
        rationale in the dispatch docstring at :648-658) — acknowledged with
        a stable marker, no state change, no error."""
        await _seed_tenant(db_session)
        payload = {
            "type": "payment.succeeded",
            "id": "fedcba98-7654-3210-fedc-ba9876543210",
            "timestamp": "2026-07-28T12:00:00.000Z",
            "data": {
                "customer_id": "dhanam-user-uuid-2",
                "subscription_id": "sub_test_456",
                "payment_id": "pi_test_789",
                "amount": "199.00",
                "amount_minor": 19900,
                "currency": "MXN",
                "plan_id": "essentials",
                "product": "dhanam",
                "payment_method": "customer_balance",
                "settlement_rail": "spei",
            },
        }
        with caplog.at_level(logging.INFO, logger=_SYNC_LOGGER):
            await handle_dhanam_billing_event(payload)
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "starter"  # unchanged
        assert "dhanam_payment_event_acknowledged" in caplog.text


class TestWebhookRoute:
    """Route-level contract: signature, dedup release, and status codes."""

    @staticmethod
    def _settings(secret: str):
        from nexus_api.config import Settings

        return Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_webhook_secret=secret,
            _env_file=None,  # type: ignore[call-arg]
        )

    @staticmethod
    def _sign(secret: str, body: bytes) -> str:
        # HMAC-SHA256 hex digest of the raw body — the scheme Dhanam uses
        # (subscription-janua-notifier.service.ts:150).
        return hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @pytest.mark.asyncio
    async def test_requires_secret(self, client) -> None:
        payload = _canonical_subscription_envelope()
        body = json.dumps(payload).encode()
        with patch(
            "nexus_api.routers.billing.get_settings", return_value=self._settings("")
        ):
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={"Content-Type": "application/json", "x-dhanam-signature": "bad"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_rejects_bad_signature(self, client) -> None:
        payload = _canonical_subscription_envelope()
        body = json.dumps(payload).encode()
        with patch(
            "nexus_api.routers.billing.get_settings",
            return_value=self._settings("test-dhanam-secret"),
        ):
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-dhanam-signature": "deadbeef",
                },
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_canonical_envelope_end_to_end(self, client, db_session) -> None:
        """Signed canonical envelope → 200 and the tier actually lands."""
        await _seed_tenant(db_session)
        secret = "test-dhanam-secret"
        payload = _canonical_subscription_envelope()
        body = json.dumps(payload).encode()
        with (
            patch(
                "nexus_api.routers.billing.get_settings",
                return_value=self._settings(secret),
            ),
            patch("nexus_api.services.billing_sync.cache_tier_limit", new=AsyncMock()),
        ):
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-dhanam-signature": self._sign(secret, body),
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "event_type": "subscription.created"}
        tenant = await _get_tenant(db_session)
        assert tenant.subscription_tier == "professional"

    @pytest.mark.asyncio
    async def test_unrecognized_envelope_returns_422_and_releases_claim(
        self, client
    ) -> None:
        """Unknown-shape envelope → non-2xx (visible to Dhanam's DLQ) and the
        dedup claim is released so a retry is not masked as a duplicate."""
        secret = "test-dhanam-secret"
        payload = {
            "type": "subscription.paused",
            "id": "deadbeef-0000-1111-2222-333333333333",
            "data": {"customer_id": "dhanam-user-uuid-1"},
            "timestamp": "2026-07-28T12:00:00.000Z",
        }
        body = json.dumps(payload).encode()
        release = AsyncMock()
        with (
            patch(
                "nexus_api.routers.billing.get_settings",
                return_value=self._settings(secret),
            ),
            patch(
                "nexus_api.routers.billing._claim_webhook_event",
                new=AsyncMock(return_value=True),
            ),
            patch("nexus_api.routers.billing._release_webhook_event", new=release),
        ):
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-dhanam-signature": self._sign(secret, body),
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["status"] == "unrecognized_envelope"
        assert detail["reason"] == "unknown_event_type"
        release.assert_awaited_once_with("deadbeef-0000-1111-2222-333333333333")


@pytest.mark.asyncio
async def test_stripe_webhook_blocked_when_billing_via_dhanam(client) -> None:
    with patch(
        "nexus_api.routers.stripe_webhooks.get_settings",
        return_value=type(
            "S",
            (),
            {
                "billing_via_dhanam": True,
                "stripe_webhook_secret": "whsec_test",
            },
        )(),
    ):
        resp = await client.post(
            "/api/v1/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=x"},
        )
    assert resp.status_code == 503
