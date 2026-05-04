"""Regression tests for the 11 webhook handlers hardened in Phase 1.

The v2.2.x security pass hardened 3 handlers (Discord / WhatsApp / generic
via _verify_hmac). Phase 1 sweeps the remaining 11 with the same fail-closed
contract: when the corresponding secret env var is unset, the endpoint
returns 503 instead of silently skipping verification.

Pre-Phase-1 behaviour (the bug): ``if settings.<secret>: <verify>`` —
falsy secret → verification skipped → handler proceeds → unauthenticated
external POST chains into a Celery ACP task with attacker-supplied URL.

Post-Phase-1 behaviour: ``_require_secret(...)`` raises 503 at the top
of every handler. Operators must set the env var to enable the endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Per-handler fixtures
# ---------------------------------------------------------------------------
# Each entry: (handler_label, http_method, path, secret_attr, env_name).
# Some handlers accept GET (verification) but post-only matters here.
_HANDLERS: list[tuple[str, str, dict[str, Any]]] = [
    (
        "telegram",
        "/api/v1/gateway/gateway/telegram/webhook",
        {
            "secret_attr": "telegram_webhook_secret",
            "env_name": "TELEGRAM_WEBHOOK_SECRET",
            "headers": {"X-Telegram-Bot-Api-Secret-Token": "anything"},
            "body": b'{"message": {"text": "/initiate_acp"}}',
        },
    ),
    (
        "slack",
        "/api/v1/gateway/gateway/slack/webhook",
        {
            "secret_attr": "slack_signing_secret",
            "env_name": "SLACK_SIGNING_SECRET",
            "headers": {
                "X-Slack-Signature": "v0=anything",
                "X-Slack-Request-Timestamp": "1700000000",
            },
            "body": b"text=&command=&user_name=test",
        },
    ),
    (
        "matrix",
        "/api/v1/gateway/gateway/matrix/webhook",
        {
            "secret_attr": "matrix_appservice_token",
            "env_name": "MATRIX_APPSERVICE_TOKEN",
            "headers": {"Authorization": "Bearer anything"},
            "body": b'{"events": []}',
        },
    ),
    (
        "mattermost",
        "/api/v1/gateway/gateway/mattermost/webhook",
        {
            "secret_attr": "mattermost_token",
            "env_name": "MATTERMOST_TOKEN",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "body": b"token=&text=&user_name=test",
        },
    ),
    (
        "twilio_sms",
        "/api/v1/gateway/gateway/sms/inbound",
        {
            "secret_attr": "twilio_auth_token",
            "env_name": "TWILIO_AUTH_TOKEN",
            "headers": {"X-Twilio-Signature": "anything"},
            "body": b"From=%2B15551234567&Body=test",
        },
    ),
    (
        "dingtalk",
        "/api/v1/gateway/gateway/dingtalk/webhook",
        {
            "secret_attr": "dingtalk_app_secret",
            "env_name": "DINGTALK_APP_SECRET",
            "headers": {"timestamp": "1700000000", "sign": "anything"},
            "body": b"{}",
        },
    ),
    (
        "feishu",
        "/api/v1/gateway/gateway/feishu/webhook",
        {
            "secret_attr": "feishu_app_secret",
            "env_name": "FEISHU_APP_SECRET",
            "headers": {
                "X-Lark-Request-Timestamp": "1700000000",
                "X-Lark-Request-Nonce": "n",
                "X-Lark-Signature": "anything",
            },
            "body": b'{"event": {}}',
        },
    ),
    (
        "wecom",
        "/api/v1/gateway/gateway/wecom/webhook?token=anything",
        {
            "secret_attr": "wecom_token",
            "env_name": "WECOM_TOKEN",
            "headers": {},
            "body": b"{}",
        },
    ),
    (
        "weixin",
        "/api/v1/gateway/gateway/weixin/webhook?appToken=anything",
        {
            "secret_attr": "weixin_app_token",
            "env_name": "WEIXIN_APP_TOKEN",
            "headers": {},
            "body": b"{}",
        },
    ),
    (
        "bluebubbles",
        "/api/v1/gateway/gateway/bluebubbles/webhook",
        {
            "secret_attr": "bluebubbles_password",
            "env_name": "BLUEBUBBLES_PASSWORD",
            "headers": {"Authorization": "Basic anything"},
            "body": b"{}",
        },
    ),
    (
        "homeassistant",
        "/api/v1/gateway/gateway/homeassistant/webhook",
        {
            "secret_attr": "ha_token",
            "env_name": "HA_TOKEN",
            "headers": {"Authorization": "Bearer anything"},
            "body": b"{}",
        },
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,path,fixture",
    [(label, path, fixture) for label, path, fixture in _HANDLERS],
    ids=[label for label, _path, _fixture in _HANDLERS],
)
class TestRemainingWebhooksFailClosed:
    """For every handler, an empty secret MUST yield 503."""

    async def test_returns_503_when_secret_unset(
        self,
        client: httpx.AsyncClient,
        caplog: pytest.LogCaptureFixture,
        label: str,
        path: str,
        fixture: dict[str, Any],
    ) -> None:
        """Empty secret → 503 + ERROR log naming the env var."""
        from nexus_api.config import get_settings

        caplog.set_level(logging.ERROR, logger="nexus_api.routers.gateway")
        settings = get_settings()
        original = getattr(settings, fixture["secret_attr"], None)
        setattr(settings, fixture["secret_attr"], "")

        try:
            resp = await client.post(
                path,
                content=fixture["body"],
                headers=fixture["headers"],
            )
            assert resp.status_code == 503, (
                f"{label}: expected 503 with empty {fixture['env_name']}, "
                f"got {resp.status_code}: {resp.text}"
            )
            assert "not configured" in resp.json()["detail"].lower()
            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert any(
                fixture["env_name"] in r.getMessage() for r in error_records
            ), f"{label}: expected ERROR log naming {fixture['env_name']}"
        finally:
            setattr(settings, fixture["secret_attr"], original)
