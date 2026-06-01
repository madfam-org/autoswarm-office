"""RFC 0008 Sprint 1 — tests for the ``webhooks.*`` tool family.

Invariants under test (each maps to one or more tests below):

1.  Stripe create happy path — provider API is called, signing secret
    from the response is handed to the k8s secret writer, webhook ID
    is returned, signing secret NEVER appears in any returned dict,
    log line, or audit row.
2.  Resend create happy path — same invariant as Stripe.
3.  Stripe list — returns endpoints without signing secrets.
4.  Stripe delete happy path — 204 response → status=applied, idempotent=False.
5.  Stripe delete idempotency — 404 treated as success, idempotent=True.
6.  Janua redirect register — no signing secret, still HITL-gated in prod.
7.  HITL gate per env — dev=ALLOW, staging=ASK, prod=ASK_DUAL.
8.  HITL denial in prod short-circuits before the provider API is hit.
9.  Missing API key surfaces a clean error with no leaks.
10. Provider 4xx / 5xx error handling — scrubbed error, failed audit row,
    signing secret (if any) never materialises.
11. SHA-256 URL redaction — raw URL NEVER hits the audit row; only
    an 8-hex-char prefix.
12. Audit row emission — every non-validation path writes at least one
    row; happy paths link linked_secret_audit_id for create ops.
13. Webhook secret-leakage sentinel — plaintext secret must not appear
    anywhere reachable to the caller (output, data, error, logs).
14. Source-level lint — the tool's own source references the signing
    secret only inside the CAPTURE-AND-FORWARD block.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from selva_tools.base import ToolResult
from selva_tools.builtins import webhooks as webhooks_mod
from selva_tools.builtins.webhooks import (
    JanuaOidcRedirectRegisterTool,
    Provider,
    ResendWebhookCreateTool,
    StripeWebhookCreateTool,
    StripeWebhookDeleteTool,
    StripeWebhookListTool,
    _sha256_prefix,
)

# Sentinels that MUST NEVER appear in logs, returned data, audit rows, or errors.
STRIPE_SIGNING_SECRET = "DUMMY_WEBHOOK_SECRET_DO_NOT_USE_stripe_DO_NOT_LEAK_aaaaaaaa"
RESEND_SIGNING_SECRET = "resend_DUMMY_WEBHOOK_SECRET_DO_NOT_USE"
STRIPE_API_KEY = "sk_test_FAKE_KEY_DO_NOT_LEAK_cccccccc"
RESEND_API_KEY = "re_test_FAKE_KEY_DO_NOT_LEAK_dddddddd"
JANUA_ADMIN_TOKEN = "janua_admin_DO_NOT_LEAK_eeeeeeee"

STRIPE_URL = "https://api.dhan.am/v1/billing/webhooks/stripe?tok=SENSITIVE-PATH-TOKEN"
RESEND_URL = "https://api.madfam.io/v1/webhooks/resend"
JANUA_REDIRECT_URI = "https://office.madfam.io/auth/callback"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point SELVA_ENV at dev so HITL defaults to ALLOW for most tests."""
    monkeypatch.setenv("SELVA_ENV", "dev")
    # Provider keys available via env — individual tests may clear them.
    monkeypatch.setenv("STRIPE_MX_SECRET_KEY", STRIPE_API_KEY)
    monkeypatch.setenv("RESEND_API_KEY", RESEND_API_KEY)
    monkeypatch.setenv("JANUA_ADMIN_API_KEY", JANUA_ADMIN_TOKEN)


@pytest.fixture
def audit_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture every webhook-audit call made by the tool."""
    spy: dict[str, Any] = {"rows": []}

    def fake_append(**kwargs: Any) -> str | None:
        spy["rows"].append(kwargs)
        # Return a fake UUID so the callee can back-link it.
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(
        webhooks_mod,
        "_audit_webhook",
        fake_append,
        raising=True,
    )
    return spy


@pytest.fixture
def secret_writer_spy() -> MagicMock:
    """A mock KubernetesSecretWriteTool that records the write and
    succeeds — without touching k8s or the secret-audit DB."""

    writer = MagicMock(name="KubernetesSecretWriteTool")

    async def fake_execute(**kwargs: Any) -> ToolResult:
        # Record the full call kwargs so tests can assert on them.
        writer.recorded.append(kwargs)
        return ToolResult(
            success=True,
            output="k8s secret written (mock)",
            data={
                "approval_request_id": "22222222-2222-2222-2222-222222222222",
                "status": "applied",
                "value_sha256_prefix": kwargs["value"][:8]
                if isinstance(kwargs.get("value"), str)
                else "00000000",
                "hitl_level": "allow",
            },
        )

    writer.recorded = []
    writer.execute = fake_execute
    return writer


def _mock_httpx_client_with_handler(
    handler: Any,
) -> httpx.Client:
    """Build a sync httpx.Client with a MockTransport routing to ``handler``."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def _base_stripe_create_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "account_id": "stripe-mx",
        "url": STRIPE_URL,
        "events": ["payment_intent.succeeded"],
        "api_key_env": "STRIPE_MX_SECRET_KEY",
        "destination_cluster": "madfam-dev",
        "destination_namespace": "autoswarm-office",
        "destination_secret_name": "dhanam-secrets",
        "destination_secret_key": "STRIPE_MX_WEBHOOK_SECRET",
        "rationale": "initial webhook setup for dhanam billing relay",
        "agent_id": None,
        "actor_user_sub": "auth0|tester",
    }
    args.update(overrides)
    return args


def _base_resend_create_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "url": RESEND_URL,
        "events": ["email.sent"],
        "api_key_env": "RESEND_API_KEY",
        "destination_cluster": "madfam-dev",
        "destination_namespace": "autoswarm-office",
        "destination_secret_name": "autoswarm-office-secrets",
        "destination_secret_key": "RESEND_WEBHOOK_SECRET",
        "rationale": "initial webhook setup for resend bounce events",
    }
    args.update(overrides)
    return args


def _assert_no_leak(blob: str, *, extra: list[str] | None = None) -> None:
    """Guard every surface we can reach against plaintext sensitive values."""
    forbidden = [
        STRIPE_SIGNING_SECRET,
        RESEND_SIGNING_SECRET,
        STRIPE_API_KEY,
        RESEND_API_KEY,
        JANUA_ADMIN_TOKEN,
    ]
    if extra:
        forbidden.extend(extra)
    for v in forbidden:
        assert v not in blob, f"sensitive value leaked: {v[:16]}..."


# ---------------------------------------------------------------------------
# 1. Stripe create — happy path + leak guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_create_captures_secret_and_never_leaks(
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Happy path: Stripe API returns secret → k8s writer called → no leak."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.webhooks")

    request_log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        return httpx.Response(
            200,
            json={
                "id": "we_test_123",
                "url": STRIPE_URL,
                "enabled_events": ["payment_intent.succeeded"],
                "secret": STRIPE_SIGNING_SECRET,
                "status": "enabled",
            },
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )

    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["provider"] == Provider.STRIPE.value
    assert result.data["webhook_id"] == "we_test_123"
    assert result.data["target_url_sha256_prefix"] == _sha256_prefix(STRIPE_URL)

    # The secret writer was called exactly once with the captured secret.
    assert len(secret_writer_spy.recorded) == 1
    call = secret_writer_spy.recorded[0]
    assert call["value"] == STRIPE_SIGNING_SECRET
    assert call["cluster"] == "madfam-dev"
    assert call["namespace"] == "autoswarm-office"
    assert call["secret_name"] == "dhanam-secrets"
    assert call["key"] == "STRIPE_MX_WEBHOOK_SECRET"
    assert call["source"] == "stripe_api"

    # The signing secret must NOT appear in output, data, error, logs,
    # or the audit row.
    _assert_no_leak(result.output or "")
    _assert_no_leak(json.dumps(result.data, default=str))
    _assert_no_leak(result.error or "")
    for rec in caplog.records:
        _assert_no_leak(rec.getMessage())

    assert len(audit_spy["rows"]) == 1
    row = audit_spy["rows"][0]
    assert row["status"] == "applied"
    assert row["provider"] == "stripe"
    assert row["action"] == "create"
    assert row["webhook_id"] == "we_test_123"
    # URL is redacted.
    assert row["target_url_sha256_prefix"] == _sha256_prefix(STRIPE_URL)
    assert STRIPE_URL not in json.dumps(row, default=str)
    # Linked secret audit id is populated.
    assert row["linked_secret_audit_id"] == "22222222-2222-2222-2222-222222222222"
    # Signing secret does not appear in audit row.
    assert STRIPE_SIGNING_SECRET not in json.dumps(row, default=str)


# ---------------------------------------------------------------------------
# 2. Resend create — happy path + leak guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resend_create_captures_secret_and_never_leaks(
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resend's signing_secret is captured and passed to the writer; no leak."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.webhooks")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/webhooks"
        return httpx.Response(
            200,
            json={
                "id": "wh_resend_456",
                "endpoint_url": RESEND_URL,
                "signing_secret": RESEND_SIGNING_SECRET,
            },
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = ResendWebhookCreateTool()
    result = await tool.execute(
        **_base_resend_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )

    assert result.success is True, result.error
    assert result.data["webhook_id"] == "wh_resend_456"
    assert result.data["provider"] == Provider.RESEND.value

    assert len(secret_writer_spy.recorded) == 1
    assert secret_writer_spy.recorded[0]["value"] == RESEND_SIGNING_SECRET
    assert secret_writer_spy.recorded[0]["key"] == "RESEND_WEBHOOK_SECRET"

    _assert_no_leak(result.output or "")
    _assert_no_leak(json.dumps(result.data, default=str))
    for rec in caplog.records:
        _assert_no_leak(rec.getMessage())

    assert len(audit_spy["rows"]) == 1
    assert audit_spy["rows"][0]["provider"] == "resend"
    assert RESEND_SIGNING_SECRET not in json.dumps(audit_spy["rows"][0], default=str)


# ---------------------------------------------------------------------------
# 3. Stripe list — read-only, no secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_list_returns_endpoints_without_secrets(
    audit_spy: dict[str, Any],
) -> None:
    """List returns IDs and URLs; never surfaces signing secrets."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/webhook_endpoints"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "we_1",
                        "url": "https://api.dhan.am/v1/billing/webhooks/stripe",
                        "enabled_events": ["payment_intent.succeeded"],
                        "status": "enabled",
                        "created": 1700000000,
                    },
                    {
                        "id": "we_2",
                        "url": "https://staging-api.dhan.am/v1/billing/webhooks/stripe",
                        "enabled_events": ["checkout.session.completed"],
                        "status": "disabled",
                        "created": 1700100000,
                    },
                ]
            },
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookListTool()
    result = await tool.execute(
        api_key_env="STRIPE_MX_SECRET_KEY",
        account_id="stripe-mx",
        _http_client=client,
    )

    assert result.success is True
    assert result.data["count"] == 2
    ids = [ep["id"] for ep in result.data["endpoints"]]
    assert ids == ["we_1", "we_2"]
    # No "secret" key on any endpoint summary.
    for ep in result.data["endpoints"]:
        assert "secret" not in ep
    # Audit row is emitted with action=list, no linked secret.
    assert len(audit_spy["rows"]) == 1
    assert audit_spy["rows"][0]["action"] == "list"
    assert audit_spy["rows"][0]["linked_secret_audit_id"] is None


# ---------------------------------------------------------------------------
# 4 & 5. Stripe delete — happy path + idempotent 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_delete_happy_path(audit_spy: dict[str, Any]) -> None:
    """Normal delete → status=applied, idempotent=False."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={"id": "we_test_123", "deleted": True})

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookDeleteTool()
    result = await tool.execute(
        webhook_id="we_test_123",
        api_key_env="STRIPE_MX_SECRET_KEY",
        account_id="stripe-mx",
        rationale="retiring unmanaged dashboard webhook per RFC 0008",
        _http_client=client,
    )
    assert result.success is True
    assert result.data["status"] == "applied"
    assert result.data["idempotent"] is False


@pytest.mark.asyncio
async def test_stripe_delete_is_idempotent_on_404(
    audit_spy: dict[str, Any],
) -> None:
    """404 from provider is treated as success with idempotent=True."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookDeleteTool()
    result = await tool.execute(
        webhook_id="we_already_gone",
        api_key_env="STRIPE_MX_SECRET_KEY",
        rationale="cleanup of already-deleted webhook",
        _http_client=client,
    )
    assert result.success is True
    assert result.data["idempotent"] is True
    assert audit_spy["rows"][0]["status"] == "applied"


# ---------------------------------------------------------------------------
# 6. Janua OIDC redirect register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_janua_redirect_register_happy_path(
    audit_spy: dict[str, Any],
) -> None:
    """Redirect URI registers, audit row emitted, admin token never logged."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        body = json.loads(request.content.decode())
        assert body == {"add_redirect_uri": JANUA_REDIRECT_URI}
        return httpx.Response(
            200,
            json={"client_id": "client_xyz", "redirect_uris": [JANUA_REDIRECT_URI]},
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = JanuaOidcRedirectRegisterTool()
    result = await tool.execute(
        client_id="client_xyz",
        redirect_uri=JANUA_REDIRECT_URI,
        admin_token_env="JANUA_ADMIN_API_KEY",
        rationale="registering office.madfam.io callback per RFC 0008",
        _http_client=client,
    )
    assert result.success is True
    assert result.data["status"] == "applied"
    assert result.data["provider"] == "janua"
    assert result.data["client_id"] == "client_xyz"
    assert len(audit_spy["rows"]) == 1
    row = audit_spy["rows"][0]
    assert row["action"] == "register_oidc_redirect"
    # Admin token never appears in audit row.
    assert JANUA_ADMIN_TOKEN not in json.dumps(row, default=str)


# ---------------------------------------------------------------------------
# 7. HITL gate per environment — parametrised across create tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env", "expected_status", "expected_hitl"),
    [
        ("dev", "applied", "allow"),
        ("staging", "pending_approval", "ask"),
        ("prod", "pending_approval", "ask_dual"),
    ],
)
async def test_stripe_create_hitl_per_env(
    monkeypatch: pytest.MonkeyPatch,
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
    env: str,
    expected_status: str,
    expected_hitl: str,
) -> None:
    """dev=ALLOW applies immediately; staging=ASK and prod=ASK_DUAL
    return pending_approval WITHOUT calling the provider."""
    monkeypatch.setenv("SELVA_ENV", env)

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            200,
            json={
                "id": "we_test_hitl",
                "secret": STRIPE_SIGNING_SECRET,
                "url": STRIPE_URL,
            },
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is True, result.error
    assert result.data["status"] == expected_status
    assert result.data["hitl_level"] == expected_hitl

    if expected_status == "pending_approval":
        # Provider API and secret writer MUST NOT have been touched.
        assert call_count["n"] == 0
        assert len(secret_writer_spy.recorded) == 0
        # Audit row recorded as pending.
        assert audit_spy["rows"][0]["status"] == "pending_approval"
    else:
        assert call_count["n"] == 1
        assert len(secret_writer_spy.recorded) == 1


@pytest.mark.asyncio
async def test_stripe_list_allows_in_prod(
    monkeypatch: pytest.MonkeyPatch, audit_spy: dict[str, Any]
) -> None:
    """List never requires approval — always ALLOW."""
    monkeypatch.setenv("SELVA_ENV", "prod")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookListTool()
    result = await tool.execute(api_key_env="STRIPE_MX_SECRET_KEY", _http_client=client)
    assert result.success is True
    assert result.data["hitl_level"] == "allow"
    assert result.data["count"] == 0


# ---------------------------------------------------------------------------
# 8. HITL denial short-circuits (prod create doesn't call provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prod_create_does_not_touch_provider_api(
    monkeypatch: pytest.MonkeyPatch,
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
) -> None:
    """Prod create MUST NOT call Stripe API or secret writer pre-approval.

    This is the "rogue webhook exfiltration" mitigation per RFC 0008.
    """
    monkeypatch.setenv("SELVA_ENV", "prod")
    tripped = {"api": False}

    def handler(request: httpx.Request) -> httpx.Response:
        tripped["api"] = True
        return httpx.Response(500, json={})

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is True
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask_dual"
    assert tripped["api"] is False
    assert len(secret_writer_spy.recorded) == 0


# ---------------------------------------------------------------------------
# 9. Missing provider API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_create_without_api_key_env_errors_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
) -> None:
    """Missing env var → clean error, failed audit row, no leak, no provider call."""
    monkeypatch.delenv("STRIPE_MX_SECRET_KEY", raising=False)
    tripped = {"api": False}

    def handler(request: httpx.Request) -> httpx.Response:
        tripped["api"] = True
        return httpx.Response(500)

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is False
    assert "STRIPE_MX_SECRET_KEY" in (result.error or "")
    _assert_no_leak(result.error or "")
    assert tripped["api"] is False
    assert len(secret_writer_spy.recorded) == 0
    # Failed audit row emitted.
    assert audit_spy["rows"][-1]["status"] == "failed"


# ---------------------------------------------------------------------------
# 10. Provider 4xx / 5xx error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_create_provider_4xx_scrubbed(
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stripe 400 → error surfaced with status code only, no leak, no writer call."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.webhooks")

    def handler(request: httpx.Request) -> httpx.Response:
        # Stripe's error body sometimes echoes the API key in the
        # ``message`` field for malformed requests — emulate that to
        # ensure we don't surface provider error bodies.
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": f"Invalid auth using {STRIPE_API_KEY}",
                    "type": "invalid_request_error",
                }
            },
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is False
    # Error message says status=400 with no echo of the provider body.
    assert "status=400" in (result.error or "")
    _assert_no_leak(result.error or "")
    _assert_no_leak(result.output or "")
    for rec in caplog.records:
        _assert_no_leak(rec.getMessage())
    # Secret writer was NOT invoked.
    assert len(secret_writer_spy.recorded) == 0
    # Failed audit row.
    assert audit_spy["rows"][-1]["status"] == "failed"
    assert audit_spy["rows"][-1]["error_message"]


@pytest.mark.asyncio
async def test_stripe_create_provider_500_scrubbed(
    audit_spy: dict[str, Any], secret_writer_spy: MagicMock
) -> None:
    """5xx from Stripe surfaces cleanly; no writer call; no leak."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is False
    assert "status=503" in (result.error or "")
    assert len(secret_writer_spy.recorded) == 0


@pytest.mark.asyncio
async def test_stripe_delete_provider_500(
    audit_spy: dict[str, Any],
) -> None:
    """Delete 5xx → failed result + failed audit row (not idempotent)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookDeleteTool()
    result = await tool.execute(
        webhook_id="we_fail",
        api_key_env="STRIPE_MX_SECRET_KEY",
        rationale="testing 5xx path with a long enough reason string",
        _http_client=client,
    )
    assert result.success is False
    assert audit_spy["rows"][-1]["status"] == "failed"


# ---------------------------------------------------------------------------
# 11. URL redaction — raw URL never reaches audit row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_redacted_in_audit_row(
    audit_spy: dict[str, Any], secret_writer_spy: MagicMock
) -> None:
    """Audit row carries SHA-256 prefix only — NEVER the raw URL path."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "we_r", "secret": STRIPE_SIGNING_SECRET, "url": STRIPE_URL},
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is True

    row = audit_spy["rows"][-1]
    assert row["target_url_sha256_prefix"] == _sha256_prefix(STRIPE_URL)
    # The sensitive URL (with embedded token) MUST NOT appear in the row.
    assert "SENSITIVE-PATH-TOKEN" not in json.dumps(row, default=str)
    assert "api.dhan.am" not in json.dumps(row, default=str)


# ---------------------------------------------------------------------------
# 12. Secret response missing — graceful failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_create_without_secret_in_response_fails_cleanly(
    audit_spy: dict[str, Any], secret_writer_spy: MagicMock
) -> None:
    """Provider 200 with no ``secret`` key → failed result, writer not called."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "we_no_secret", "url": STRIPE_URL})

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    result = await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is False
    assert len(secret_writer_spy.recorded) == 0
    assert audit_spy["rows"][-1]["status"] == "failed"


# ---------------------------------------------------------------------------
# 13. Validation errors (scope: reject invalid args before touching provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"url": ""}, "url"),
        ({"url": "ftp://evil"}, "http(s)"),
        ({"rationale": "too short"}, "rationale"),
        ({"destination_cluster": "rogue-cluster"}, "destination_cluster"),
        ({"destination_namespace": "kube-system"}, "destination_namespace"),
        ({"api_key_env": ""}, "api_key_env"),
    ],
)
async def test_stripe_create_validation_rejects(
    audit_spy: dict[str, Any],
    secret_writer_spy: MagicMock,
    overrides: dict[str, Any],
    needle: str,
) -> None:
    """Bad args are rejected without hitting provider or secret writer."""
    tool = StripeWebhookCreateTool()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be hit on validation failure")

    client = _mock_httpx_client_with_handler(handler)
    result = await tool.execute(
        **_base_stripe_create_args(**overrides),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    assert result.success is False
    assert needle in (result.error or "")
    assert len(secret_writer_spy.recorded) == 0


# ---------------------------------------------------------------------------
# 14. Webhook create → signature_sha256 in audit_audit_log path fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_links_linked_secret_audit_id(
    audit_spy: dict[str, Any], secret_writer_spy: MagicMock
) -> None:
    """Happy-path create row has ``linked_secret_audit_id`` populated
    from the secret-writer's approval_request_id (the two-row audit
    chain required by RFC 0008)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "we_chain", "secret": STRIPE_SIGNING_SECRET, "url": STRIPE_URL},
        )

    client = _mock_httpx_client_with_handler(handler)
    tool = StripeWebhookCreateTool()
    await tool.execute(
        **_base_stripe_create_args(),
        _http_client=client,
        _secret_writer=secret_writer_spy,
    )
    row = audit_spy["rows"][-1]
    assert row["linked_secret_audit_id"] == "22222222-2222-2222-2222-222222222222"
    assert row["resulting_secret_name"] == (
        "autoswarm-office/dhanam-secrets:STRIPE_MX_WEBHOOK_SECRET"
    )


# ---------------------------------------------------------------------------
# 15. Source-level lint — signing secret referenced only in CAPTURE block
# ---------------------------------------------------------------------------


def _strip_strings_and_comments(source: str) -> str:
    no_comments = re.sub(r"#[^\n]*", "", source)
    no_triple = re.sub(r'"""[\s\S]*?"""', '""', no_comments)
    no_triple = re.sub(r"'''[\s\S]*?'''", "''", no_triple)
    no_strings = re.sub(r'(?:rb|br|r|b|f|rf|fr)?"(?:\\.|[^"\\\n])*"', '""', no_triple)
    no_strings = re.sub(r"(?:rb|br|r|b|f|rf|fr)?'(?:\\.|[^'\\\n])*'", "''", no_strings)
    return no_strings


def test_tool_source_never_logs_or_returns_signing_secret() -> None:
    """Lint: ``signing_secret`` only referenced inside the CAPTURE-AND-FORWARD
    block. The rest of the module must never str(), log, return, or
    interpolate it. String literals and comments are stripped first so
    docstrings mentioning ``signing_secret`` don't trip the check.
    """
    src_path = Path(webhooks_mod.__file__).resolve()
    source_raw = src_path.read_text(encoding="utf-8")
    source = _strip_strings_and_comments(source_raw)

    forbidden_patterns: list[tuple[str, str]] = [
        (r"\bstr\(\s*signing_secret\s*\)", "str(signing_secret)"),
        (r"\brepr\(\s*signing_secret\s*\)", "repr(signing_secret)"),
        (r"%\s*signing_secret\b", "% signing_secret"),
        (
            r"logger\.(?:debug|info|warning|error|critical)\([^)]*\bsigning_secret\b[^)]*\)",
            "logger.<level>(... signing_secret ...)",
        ),
        (r"\breturn\s+signing_secret\b", "return signing_secret"),
        (
            r"ToolResult\([^)]*\bsigning_secret\b[^)]*\)",
            "ToolResult(... signing_secret ...)",
        ),
        (
            r"\.format\([^)]*\bsigning_secret\b[^)]*\)",
            ".format(... signing_secret ...)",
        ),
    ]
    offenders: list[tuple[str, str]] = []
    for pattern, label in forbidden_patterns:
        for m in re.finditer(pattern, source):
            line_start = source.rfind("\n", 0, m.start()) + 1
            line_end = source.find("\n", m.end())
            if line_end == -1:
                line_end = len(source)
            offenders.append((label, source[line_start:line_end].strip()))
    assert offenders == [], f"Forbidden reference to ``signing_secret`` in tool source: {offenders}"

    # Positive check: the capture block does exist.
    assert "signing_secret = response.get(" in source_raw
    assert "signing_secret = None" in source_raw, "missing post-handoff scrub of signing_secret"


# ---------------------------------------------------------------------------
# 16. Sanity: Provider enum and _sha256_prefix
# ---------------------------------------------------------------------------


def test_provider_enum_shape() -> None:
    assert Provider.STRIPE.value == "stripe"
    assert Provider.RESEND.value == "resend"
    assert Provider.JANUA.value == "janua"


def test_sha256_prefix_is_8_hex() -> None:
    p = _sha256_prefix("https://example.com/x?tok=y")
    assert len(p) == 8
    assert all(c in "0123456789abcdef" for c in p)
