"""Regression tests for the Stripe webhook scaffold (Phase 1).

Today the endpoint verifies signatures and 200s on every event; per-event
handlers land in follow-up PRs. These tests pin the fail-closed +
signature-verification contract so the scaffold cannot silently regress
into an unauthenticated trampoline (the same class of bug the v2.2.x
gateway hardening closed for the legacy webhooks).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx
import pytest


def _build_stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Compute a valid Stripe webhook signature header for testing.

    Mirrors stripe-python's `WebhookSignature.construct_signature` so the
    tests do not depend on stripe being importable at module load time.
    Format: ``t=<timestamp>,v1=<hex-hmac>``.
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode('utf-8')}".encode()
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@pytest.mark.asyncio
class TestStripeWebhookFailClosed:
    """Endpoint MUST refuse when secret is unconfigured."""

    async def test_returns_503_when_secret_unset(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty STRIPE_WEBHOOK_SECRET → 503 (not 200, not 401).

        Matches the v2.2.x gateway hardening pattern: an unconfigured
        webhook endpoint is a misconfiguration, not a permitted state.
        """
        from nexus_api.config import get_settings

        caplog.set_level(logging.ERROR, logger="nexus_api.routers.stripe_webhooks")
        settings = get_settings()
        original_secret = settings.stripe_webhook_secret
        original_billing = settings.billing_via_dhanam
        settings.stripe_webhook_secret = ""
        settings.billing_via_dhanam = False

        try:
            resp = await client.post(
                "/api/v1/stripe/webhook",
                content=b'{"id": "evt_test", "type": "ping"}',
                headers={"stripe-signature": "t=0,v1=anything"},
            )
            assert resp.status_code == 503, (
                f"Expected 503 with empty secret, got {resp.status_code}: {resp.text}"
            )
            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert len(error_records) >= 1, "Expected ERROR log when secret unset"
            assert "stripe_webhook_secret" in error_records[0].getMessage().lower()
        finally:
            settings.stripe_webhook_secret = original_secret
            settings.billing_via_dhanam = original_billing


@pytest.mark.asyncio
class TestStripeWebhookSignature:
    """Signature verification — bad sig 401, valid sig 200."""

    async def test_returns_401_on_invalid_signature(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Wrong signature → 401 even when secret is configured."""
        from nexus_api.config import get_settings

        caplog.set_level(logging.WARNING, logger="nexus_api.routers.stripe_webhooks")
        settings = get_settings()
        original_secret = settings.stripe_webhook_secret
        original_billing = settings.billing_via_dhanam
        settings.stripe_webhook_secret = "DUMMY_WEBHOOK_SECRET_DO_NOT_USE"
        settings.billing_via_dhanam = False

        try:
            resp = await client.post(
                "/api/v1/stripe/webhook",
                content=b'{"id": "evt_test", "type": "ping"}',
                headers={"stripe-signature": "t=99999999,v1=invalid_signature_bytes"},
            )
            assert resp.status_code == 401, (
                f"Expected 401 on invalid sig, got {resp.status_code}: {resp.text}"
            )
        finally:
            settings.stripe_webhook_secret = original_secret
            settings.billing_via_dhanam = original_billing

    async def test_returns_200_on_valid_signature_unknown_event(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Valid signature for an unhandled event type → 200 + log."""
        from nexus_api.config import get_settings

        caplog.set_level(logging.INFO, logger="nexus_api.routers.stripe_webhooks")
        settings = get_settings()
        original_secret = settings.stripe_webhook_secret
        original_billing = settings.billing_via_dhanam
        settings.stripe_webhook_secret = "DUMMY_WEBHOOK_SECRET_DO_NOT_USE"
        settings.billing_via_dhanam = False

        event_payload = json.dumps(
            {
                "id": "evt_test_unknown",
                "object": "event",
                "type": "fake.event.for.test",
                "data": {"object": {}},
                "created": int(time.time()),
            }
        ).encode()
        sig_header = _build_stripe_signature(event_payload, "DUMMY_WEBHOOK_SECRET_DO_NOT_USE")

        try:
            resp = await client.post(
                "/api/v1/stripe/webhook",
                content=event_payload,
                headers={"stripe-signature": sig_header},
            )
            assert resp.status_code == 200, (
                f"Expected 200 on valid sig + unknown event, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body["status"] == "received"
            assert body["event_id"] == "evt_test_unknown"
            # Unknown handler logs at INFO so ops can see new event types
            # appear without paging.
            info_records = [
                r
                for r in caplog.records
                if r.levelno == logging.INFO
                and "no specific handler" in r.getMessage().lower()
            ]
            assert len(info_records) >= 1
        finally:
            settings.stripe_webhook_secret = original_secret
            settings.billing_via_dhanam = original_billing

    async def test_replay_outside_tolerance_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        """Old timestamp (>5 min stale) → 401 (replay attack defense)."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original_secret = settings.stripe_webhook_secret
        original_billing = settings.billing_via_dhanam
        settings.stripe_webhook_secret = "DUMMY_WEBHOOK_SECRET_DO_NOT_USE"
        settings.billing_via_dhanam = False

        # Sign a payload with a timestamp 1 hour in the past.
        event_payload = b'{"id": "evt_replay", "type": "ping"}'
        old_ts = int(time.time()) - 3600
        sig_header = _build_stripe_signature(
            event_payload, "DUMMY_WEBHOOK_SECRET_DO_NOT_USE", timestamp=old_ts
        )

        try:
            resp = await client.post(
                "/api/v1/stripe/webhook",
                content=event_payload,
                headers={"stripe-signature": sig_header},
            )
            assert resp.status_code == 401, (
                f"Expected 401 on stale signature, got {resp.status_code}: {resp.text}"
            )
        finally:
            settings.stripe_webhook_secret = original_secret
            settings.billing_via_dhanam = original_billing
