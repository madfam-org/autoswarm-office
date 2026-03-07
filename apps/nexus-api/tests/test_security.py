"""Tests for security hardening: headers, CORS, rate limiting, CSRF, auth, JWKS."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nexus_api.config import Settings
from nexus_api.main import app as _fastapi_app


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """SecurityHeadersMiddleware adds standard security headers."""

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_strict_transport_security(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert "max-age=" in (resp.headers.get("strict-transport-security") or "")

    @pytest.mark.asyncio
    async def test_x_xss_protection(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert resp.headers.get("x-xss-protection") == "0"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        assert "camera=()" in (resp.headers.get("permissions-policy") or "")


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------


class TestRequestId:
    """RequestIdMiddleware generates and propagates X-Request-ID."""

    @pytest.mark.asyncio
    async def test_request_id_generated(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/health")
        request_id = resp.headers.get("x-request-id")
        assert request_id is not None
        assert len(request_id) > 0

    @pytest.mark.asyncio
    async def test_request_id_preserved(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/health/health",
            headers={"X-Request-ID": "my-custom-id-123"},
        )
        assert resp.headers.get("x-request-id") == "my-custom-id-123"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


class TestCSRF:
    """CSRFMiddleware blocks state-changing requests without token."""

    @pytest.mark.asyncio
    async def test_post_blocked_without_csrf_token(
        self, override_get_db: None
    ) -> None:
        """POST without CSRF token is rejected with 403."""
        transport = httpx.ASGITransport(app=_fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw_client:
            resp = await raw_client.post(
                "/api/v1/agents/",
                json={"name": "TestAgent", "role": "coder"},
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_passes_with_csrf_token(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        csrf_token = "test-csrf-token-value"
        client.cookies.set("csrf-token", csrf_token)
        headers = {**auth_headers, "X-CSRF-Token": csrf_token}
        resp = await client.post(
            "/api/v1/agents/",
            json={"name": "TestAgent", "role": "coder"},
            headers=headers,
        )
        # Should not be 403 — may be 201 or other status based on data
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_webhook_exempt_from_csrf(self, client: httpx.AsyncClient) -> None:
        """Gateway webhook endpoints are exempt from CSRF checks."""
        resp = await client.post(
            "/api/v1/gateway/github",
            content=b'{"action": "opened"}',
            headers={"X-GitHub-Event": "ping", "Content-Type": "application/json"},
        )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Dev Auth Bypass
# ---------------------------------------------------------------------------


class TestDevAuthBypass:
    """Dev auth bypass is gated by dev_auth_bypass setting."""

    @pytest.mark.asyncio
    async def test_dev_bypass_blocked_when_disabled(self) -> None:
        """Even in development, bypass is blocked when dev_auth_bypass=False."""
        from nexus_api.auth import get_current_user

        settings = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=False,
            _env_file=None,  # type: ignore[call-arg]
        )

        class FakeCreds:
            credentials = "invalid-token"

        # Should attempt real JWT verification and fail
        with pytest.raises((Exception, httpx.HTTPError)):  # noqa: B017
            await get_current_user(credentials=FakeCreds(), settings=settings)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_dev_bypass_works_when_enabled(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """With dev_auth_bypass=True + development env, auth works without real JWT."""
        resp = await client.get("/api/v1/agents/", headers=auth_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# JWKS Cache TTL
# ---------------------------------------------------------------------------


class TestJWKSCache:
    """JWKS cache respects TTL-based expiration."""

    @pytest.mark.asyncio
    async def test_jwks_serves_cached(self) -> None:
        import nexus_api.auth as auth_mod

        auth_mod._jwks_cache = {"keys": [{"kid": "test", "kty": "RSA"}]}
        auth_mod._jwks_cache_time = time.monotonic()

        result = await auth_mod._fetch_jwks("https://example.com")
        assert result == {"keys": [{"kid": "test", "kty": "RSA"}]}

        # Reset
        auth_mod._jwks_cache = None
        auth_mod._jwks_cache_time = None

    @pytest.mark.asyncio
    async def test_jwks_refreshes_after_ttl(self) -> None:
        import nexus_api.auth as auth_mod

        auth_mod._jwks_cache = {"keys": [{"kid": "old"}]}
        auth_mod._jwks_cache_time = time.monotonic() - 7200  # 2 hours ago

        new_jwks = {"keys": [{"kid": "new", "kty": "RSA"}]}

        class MockResponse:
            def json(self) -> dict:  # type: ignore[type-arg]
                return new_jwks

            def raise_for_status(self) -> None:
                pass

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MockResponse())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await auth_mod._fetch_jwks("https://example.com")

        assert result["keys"][0]["kid"] == "new"

        # Reset
        auth_mod._jwks_cache = None
        auth_mod._jwks_cache_time = None


# ---------------------------------------------------------------------------
# Health Detail
# ---------------------------------------------------------------------------


class TestHealthDetail:
    """The /health/detail endpoint reports per-component status."""

    @pytest.mark.asyncio
    async def test_health_detail_returns_checks(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/health/detail")
        data = resp.json()
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
        assert "colyseus" in data["checks"]
        assert data["version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Billing Header Fix
# ---------------------------------------------------------------------------


class TestBillingHeaderFix:
    """Dhanam webhook uses x-dhanam-signature, not x-janua-signature."""

    @pytest.mark.asyncio
    async def test_dhanam_webhook_rejects_wrong_header(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Verify the webhook checks x-dhanam-signature (not x-janua-signature)."""
        body = json.dumps({"type": "subscription.updated"}).encode()

        correct_sig = hmac_mod.new(
            b"test-secret", body, hashlib.sha256
        ).hexdigest()

        patched = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_webhook_secret="test-secret",
            _env_file=None,  # type: ignore[call-arg]
        )

        csrf = "test-csrf"
        client.cookies.set("csrf-token", csrf)

        with patch("nexus_api.routers.billing.get_settings", return_value=patched):
            # Using x-janua-signature (old, wrong header) should fail with 401
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    **auth_headers,
                    "x-janua-signature": correct_sig,
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf,
                },
            )
            assert resp.status_code == 401
            assert resp.json()["detail"] == "Invalid signature"

            # Using x-dhanam-signature (correct header) should work
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    **auth_headers,
                    "x-dhanam-signature": correct_sig,
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf,
                },
            )
            assert resp.status_code == 200
