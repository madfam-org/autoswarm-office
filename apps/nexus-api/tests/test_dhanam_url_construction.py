"""Every Dhanam URL this service builds, pinned as a literal string.

Dhanam serves its whole API under ``/v1`` while ``DHANAM_API_URL`` is a bare
origin, so the version segment is ours to add. It was missing from the billing
client and from the portal route, and no test noticed: the checkout tests all
patched ``DhanamClient.create_checkout`` itself, so no test ever built a URL.

These go the other way round — the client is real and only the transport is
mocked, so what gets asserted is the exact string that would go on the wire.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from nexus_api.billing_client import DhanamClient, get_billing_status
from nexus_api.config import Settings

# Captured before any patching so the injecting factory below can still build
# a genuine client.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

_DHANAM_URL = "https://api.dhan.am"


def _settings_with_dhanam(url: str = _DHANAM_URL) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_api_url=url,
        dhanam_webhook_secret="test-secret",
        public_app_url="https://app.selva.town",
        _env_file=None,  # type: ignore[call-arg]
    )


class _Recorder:
    """Records every request an httpx client sends, answering with a canned
    response. Replaces the transport, never the method under test — patching
    the method is what let the malformed URL through."""

    def __init__(self, status_code: int = 200, body: dict[str, Any] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status_code = status_code
        self._body = body if body is not None else {"url": "https://checkout.dhan.am/sess_1"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._body)

    @property
    def url(self) -> str:
        """The single URL dialled, asserting there was exactly one."""
        assert len(self.requests) == 1, f"expected 1 outbound request, got {len(self.requests)}"
        return str(self.requests[0].url)


def _async_client_factory(recorder: _Recorder) -> Callable[..., httpx.AsyncClient]:
    """Build a drop-in for ``httpx.AsyncClient`` that routes to ``recorder``."""
    transport = httpx.MockTransport(recorder)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    return factory


def _intercept(recorder: _Recorder) -> Any:
    return patch("httpx.AsyncClient", _async_client_factory(recorder))


@pytest.mark.asyncio
class TestDhanamClientUrls:
    """Each ``DhanamClient`` method, asserted against the full URL."""

    async def test_status(self) -> None:
        rec = _Recorder(body={"tier": "starter"})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).get_status("tok")
        assert rec.url == "https://api.dhan.am/v1/billing/status"

    async def test_usage(self) -> None:
        rec = _Recorder(body={"used": 0})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).get_usage("tok")
        assert rec.url == "https://api.dhan.am/v1/billing/usage"

    async def test_portal(self) -> None:
        rec = _Recorder(body={"url": "https://portal.dhan.am/s"})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).create_portal_session("tok")
        assert rec.url == "https://api.dhan.am/v1/billing/portal"

    async def test_checkout(self) -> None:
        rec = _Recorder()
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).create_checkout(
                "tok",
                tier="professional",
                success_url="https://app.selva.town/office",
                cancel_url="https://app.selva.town/pricing",
            )
        assert rec.url == "https://api.dhan.am/v1/billing/checkout"

    async def test_catalog(self) -> None:
        rec = _Recorder(body={"products": []})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).get_catalog()
        assert rec.url == "https://api.dhan.am/v1/billing/catalog"

    async def test_catalog_single_product(self) -> None:
        rec = _Recorder(body={"slug": "selva-pro"})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).get_catalog("selva-pro")
        assert rec.url == "https://api.dhan.am/v1/billing/catalog/selva-pro"

    async def test_base_already_versioned_is_not_double_prefixed(self) -> None:
        """Re-pointing DHANAM_API_URL at a versioned URL must not yield /v1/v1."""
        rec = _Recorder()
        with _intercept(rec):
            await DhanamClient("https://api.dhan.am/v1/").create_checkout(
                "tok",
                tier="starter",
                success_url="https://app.selva.town/office",
                cancel_url="https://app.selva.town/pricing",
            )
        assert rec.url == "https://api.dhan.am/v1/billing/checkout"

    async def test_trailing_slash_base(self) -> None:
        rec = _Recorder(body={"tier": "starter"})
        with _intercept(rec):
            await DhanamClient("https://api.dhan.am/").get_status("tok")
        assert rec.url == "https://api.dhan.am/v1/billing/status"


@pytest.mark.asyncio
class TestBudgetLookupUrl:
    async def test_space_budget(self) -> None:
        rec = _Recorder(body={"compute_tokens_remaining": 10})
        with (
            patch("nexus_api.config.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            await get_billing_status("space_abc")
        assert rec.url == "https://api.dhan.am/v1/spaces/space_abc/budget"


@pytest.mark.asyncio
class TestBillingRouterUrls:
    """The URLs the billing routes dial, driven through the real app."""

    async def test_portal_route(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rec = _Recorder(body={"url": "https://portal.dhan.am/s"})
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post("/api/v1/billing/portal", headers=auth_headers)
        assert resp.status_code == 200
        assert rec.url == "https://api.dhan.am/v1/billing/portal"

    async def test_portal_route_without_dhanam_url_still_degrades(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Default test settings carry no dhanam_api_url. Routing the portal
        through DhanamClient must keep that a 502, never a 500 traceback."""
        resp = await client.post("/api/v1/billing/portal", headers=auth_headers)
        assert resp.status_code == 502

    async def test_checkout_route(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rec = _Recorder()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert rec.url == "https://api.dhan.am/v1/billing/checkout"

    async def test_status_route(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rec = _Recorder(body={"tier": "starter", "is_active": True})
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.get("/api/v1/billing/status", headers=auth_headers)
        assert resp.status_code == 200
        assert rec.url == "https://api.dhan.am/v1/subscription/status"


@pytest.mark.asyncio
class TestCheckoutUpstreamErrors:
    """A 404 is our malformed request, not a missing Dhanam feature."""

    async def test_404_is_502_and_logs_the_url(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.ERROR, logger="nexus_api.routers.billing")
        rec = _Recorder(status_code=404, body={"detail": "Not Found"})
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 502
        # The operator gets the URL...
        assert any(
            "https://api.dhan.am/v1/billing/checkout" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        ), "the attempted Dhanam URL must be logged"
        # ...the caller does not: this route is public.
        assert "api.dhan.am" not in resp.text

    async def test_5xx_is_502(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rec = _Recorder(status_code=503, body={"detail": "upstream down"})
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 502
