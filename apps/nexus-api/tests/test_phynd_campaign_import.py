"""Tests for the Selva → PhyndCRM campaign-import bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus_api.services import phynd_campaign_import as bridge


def _settings(url: str | None, secret: str) -> MagicMock:
    s = MagicMock()
    s.phynd_crm_url = url
    s.phynd_campaign_import_secret = secret
    return s


def test_build_payload_maps_handoff_to_import_schema() -> None:
    payload = bridge.build_campaign_import_payload(
        handoff_id="h-1",
        sku_key="avala__issuer",
        platform="avala",
        audience="credential issuers",
        campaign_name="avala issuers",
        value_prop="Issue verifiable credentials fast.",
        ga_readiness="ready",
        draft_variants=[{"format": "structured", "subject": "S", "body": "B"}],
        proof_points=[{"label": "X", "detail": "Y"}],
    )
    assert payload["idempotency_key"] == "selva-handoff:h-1:avala__issuer"
    assert payload["source"] == "selva"
    assert payload["sku_key"] == "avala__issuer"
    assert payload["platform"] == "avala"
    assert payload["audience"] == "credential issuers"
    assert payload["ga_readiness"] == "ready"
    assert payload["value_prop"].startswith("Issue")
    assert payload["draft_variants"][0]["subject"] == "S"


def test_ga_readiness_tolerates_pricing_vocabulary() -> None:
    p = bridge.build_campaign_import_payload(
        handoff_id="h",
        sku_key="s",
        platform="p",
        audience=None,
        campaign_name="c",
        value_prop="v",
        ga_readiness="ga_ready",  # pricing-side term
        draft_variants=[{"body": "b"}],
    )
    assert p["ga_readiness"] == "ready"
    # audience omitted cleanly when None
    assert "audience" not in p


@pytest.mark.asyncio
async def test_push_is_skipped_when_unconfigured() -> None:
    with patch.object(bridge, "get_settings", return_value=_settings(None, "")):
        result = await bridge.push_campaign_import({"sku_key": "s"})
    assert result == {"status": "skipped", "reason": "not_configured"}


@pytest.mark.asyncio
async def test_push_signs_and_posts_when_configured() -> None:
    secret = "shared-hmac-secret"
    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = "ok"

    async def _post(url, content, headers):  # noqa: ANN001
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        return _Resp()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = _post

    with (
        patch.object(
            bridge, "get_settings", return_value=_settings("https://crm.test", secret)
        ),
        patch.object(bridge.httpx, "AsyncClient", return_value=mock_client),
    ):
        result = await bridge.push_campaign_import({"sku_key": "s", "value_prop": "v"})

    assert result == {"status": "sent", "http_status": 200}
    assert captured["url"] == "https://crm.test/api/v1/campaigns/import"

    # Signature must be HMAC-SHA256(secret, raw body) hex, sha256= prefixed —
    # exactly what PhyndCRM's validateWebhookSignature verifies.
    body = captured["content"]
    expected = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["x-webhook-signature"] == expected
    # body is valid JSON of the payload
    assert json.loads(body)["sku_key"] == "s"


@pytest.mark.asyncio
async def test_push_never_raises_on_transport_error() -> None:
    with (
        patch.object(
            bridge, "get_settings", return_value=_settings("https://crm.test", "sec")
        ),
        patch.object(
            bridge.httpx,
            "AsyncClient",
            side_effect=bridge.httpx.ConnectError("down"),
        ),
    ):
        result = await bridge.push_campaign_import({"sku_key": "s"})
    assert result["status"] == "error"
