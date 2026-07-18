"""Tests for security hardening: headers, CORS, rate limiting, CSRF, auth, JWKS."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

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
        policy = resp.headers.get("permissions-policy") or ""
        assert "camera=(self)" in policy
        assert "microphone=(self)" in policy
        assert "geolocation=()" in policy


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
    async def test_post_blocked_without_csrf_or_bearer(self, override_get_db: None) -> None:
        """POST without CSRF token or Bearer auth is rejected with 403."""
        transport = httpx.ASGITransport(app=_fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw_client:
            resp = await raw_client.post(
                "/api/v1/agents/",
                json={"name": "TestAgent", "role": "coder"},
            )
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_bearer_auth_bypasses_csrf(self, override_get_db: None) -> None:
        """Bearer-authenticated requests skip CSRF validation (tokens are CSRF-safe)."""
        transport = httpx.ASGITransport(app=_fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw_client:
            resp = await raw_client.post(
                "/api/v1/agents/",
                json={"name": "TestAgent", "role": "coder"},
                headers={"Authorization": "Bearer test-token"},
            )
            # Should not be 403 — Bearer token bypasses CSRF
            assert resp.status_code != 403

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

        correct_sig = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()

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

    @pytest.mark.asyncio
    async def test_dhanam_webhook_ignores_replayed_event(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A re-delivered event id is dropped (first-write-wins idempotency),
        so a replayed subscription.deleted can't downgrade a paying tenant."""
        body = json.dumps(
            {"id": "evt_replay_1", "type": "subscription.deleted", "data": {"org_id": "acme"}}
        ).encode()
        sig = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()
        patched = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_webhook_secret="test-secret",
            _env_file=None,  # type: ignore[call-arg]
        )
        csrf = "test-csrf"
        client.cookies.set("csrf-token", csrf)

        # First delivery claims the id (SET NX → truthy), replay does not.
        claims = iter([True, None])

        async def fake_claim(op: str, *a: object, **k: object) -> object:
            if op == "set":
                return next(claims, None)
            return None

        mock_pool = MagicMock()
        mock_pool.execute_with_retry = AsyncMock(side_effect=fake_claim)
        handler = AsyncMock()

        req_headers = {
            **auth_headers,
            "x-dhanam-signature": sig,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
        }

        with (
            patch("nexus_api.routers.billing.get_settings", return_value=patched),
            patch("selva_redis_pool.get_redis_pool", return_value=mock_pool),
            patch(
                "nexus_api.services.billing_sync.handle_dhanam_billing_event",
                handler,
            ),
        ):
            first = await client.post(
                "/api/v1/billing/webhooks/dhanam", content=body, headers=req_headers
            )
            second = await client.post(
                "/api/v1/billing/webhooks/dhanam", content=body, headers=req_headers
            )

        assert first.status_code == 200
        assert first.json()["status"] == "ok"
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"
        # The billing state handler ran exactly once, not for the replay.
        assert handler.await_count == 1


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


def _make_mock_pool(execute_return: list[object] | None = None) -> MagicMock:
    """Build a mock RedisPool that returns a mock client with pipeline support.

    *execute_return* controls what ``pipeline.execute()`` resolves to.
    Defaults to ``[1, True]`` (first request, within limit).
    """
    if execute_return is None:
        execute_return = [1, True]

    mock_pipe = MagicMock()
    mock_pipe.incr = AsyncMock()
    mock_pipe.expire = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=execute_return)

    mock_client = MagicMock()
    mock_client.pipeline.return_value = mock_pipe

    mock_pool = MagicMock()
    mock_pool.client = AsyncMock(return_value=mock_client)

    return mock_pool, mock_client


class TestRateLimiting:
    """RateLimitMiddleware enforces per-IP request quotas via Redis."""

    @pytest.mark.asyncio
    async def test_health_endpoint_exempt(self, client: httpx.AsyncClient) -> None:
        """Requests to /api/v1/health/* must never receive 429."""
        mock_pool, mock_client = _make_mock_pool()
        with patch(
            "nexus_api.middleware.rate_limit.get_redis_pool",
            return_value=mock_pool,
        ):
            for _ in range(100):
                resp = await client.get("/api/v1/health/health")
                assert resp.status_code != 429

        # Redis should never have been called for health endpoints.
        mock_client.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """After exceeding the limit, the middleware returns 429 with Retry-After."""
        # Simulate a count of 61 (over the 60 req/min default limit).
        mock_pool, _ = _make_mock_pool(execute_return=[61, True])

        with patch(
            "nexus_api.middleware.rate_limit.get_redis_pool",
            return_value=mock_pool,
        ):
            resp = await client.get("/api/v1/agents/", headers=auth_headers)
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert int(resp.headers["Retry-After"]) > 0
            body = resp.json()
            assert body["detail"] == "Rate limit exceeded"

    @pytest.mark.asyncio
    async def test_redis_failure_allows_request(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """When Redis is unavailable, requests pass through (fail-open)."""
        with patch(
            "nexus_api.middleware.rate_limit.get_redis_pool",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            resp = await client.get("/api/v1/agents/", headers=auth_headers)
            # Should NOT be 429 -- middleware falls back to allowing the request.
            assert resp.status_code != 429
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_under_limit_request_passes(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Requests under the rate limit are forwarded normally."""
        mock_pool, _ = _make_mock_pool(execute_return=[1, True])

        with patch(
            "nexus_api.middleware.rate_limit.get_redis_pool",
            return_value=mock_pool,
        ):
            resp = await client.get("/api/v1/agents/", headers=auth_headers)
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_redis_pipeline_error_allows_request(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A Redis error during pipeline execution still allows the request."""
        mock_pipe = MagicMock()
        mock_pipe.incr = AsyncMock()
        mock_pipe.expire = AsyncMock()
        mock_pipe.execute = AsyncMock(side_effect=Exception("pipeline broken"))

        mock_client = MagicMock()
        mock_client.pipeline.return_value = mock_pipe

        mock_pool = MagicMock()
        mock_pool.client = AsyncMock(return_value=mock_client)

        with patch(
            "nexus_api.middleware.rate_limit.get_redis_pool",
            return_value=mock_pool,
        ):
            resp = await client.get("/api/v1/agents/", headers=auth_headers)
            assert resp.status_code != 429
            assert resp.status_code == 200
