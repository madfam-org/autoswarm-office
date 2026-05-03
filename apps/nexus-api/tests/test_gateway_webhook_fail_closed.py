"""Regression tests for the webhook signature fail-closed fix.

Pre-fix behaviour (commit before e71337c): ``_verify_hmac`` returned
``True`` when the secret was an empty string -- meaning every webhook
handler whose secret env var defaulted to ``""`` (Discord, WhatsApp, the
generic gateway, etc.) accepted unauthenticated POSTs from the public
internet. The Discord handler chained into Celery task creation with an
attacker-supplied URL.

Post-fix behaviour: ``_verify_hmac`` returns ``False`` on empty secret
with an ``ERROR``-level log explaining ops needs to set the env var.
The Discord route now returns 503 when the secret is unconfigured,
preventing accidental fail-open.

These tests pin the new behaviour so the regression cannot silently
return.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx
import pytest

from nexus_api.routers.gateway import _verify_hmac


class TestVerifyHmacUnit:
    """Unit tests for the _verify_hmac helper."""

    def test_verify_hmac_returns_false_on_empty_secret(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty secret MUST refuse verification (not fail-open)."""
        caplog.set_level(logging.ERROR, logger="nexus_api.routers.gateway")

        result = _verify_hmac(b"any-payload", "sha256=anything", "")

        assert result is False
        # An ERROR-level log MUST fire so ops sees the misconfiguration.
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1, "Expected an ERROR log when secret is empty"
        assert "empty secret" in error_records[0].getMessage().lower()

    def test_verify_hmac_returns_false_on_bad_signature(self) -> None:
        """Wrong signature with valid secret returns False."""
        result = _verify_hmac(b"payload", "sha256=wrong", "real-secret")
        assert result is False

    def test_verify_hmac_returns_true_on_valid_signature(self) -> None:
        """Correctly computed HMAC-SHA256 verifies."""
        body = b"some-webhook-payload"
        secret = "real-secret-value"
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        assert _verify_hmac(body, expected, secret) is True


@pytest.mark.asyncio
class TestDiscordWebhookFailClosed:
    """Integration test: the Discord webhook MUST refuse when secret unset."""

    async def test_discord_webhook_returns_503_when_secret_unset(
        self, client: httpx.AsyncClient
    ) -> None:
        """Empty discord_webhook_secret yields 503 (not 200, not 401).

        Pre-fix this would have returned 200 because ``_verify_hmac("", ...)``
        returned True. Now the route refuses early with 503 because the
        endpoint is disabled when no secret is configured.
        """
        from nexus_api.config import get_settings

        settings = get_settings()
        original_secret = settings.discord_webhook_secret
        settings.discord_webhook_secret = ""

        try:
            resp = await client.post(
                "/api/v1/gateway/gateway/discord/webhook",
                content=b'{"content": "/status"}',
                headers={"X-Signature-256": "sha256=anything"},
            )
            assert resp.status_code == 503, (
                f"Expected 503 with empty secret, got {resp.status_code}: {resp.text}"
            )
            assert "not configured" in resp.json()["detail"].lower()
        finally:
            settings.discord_webhook_secret = original_secret
