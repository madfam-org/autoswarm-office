"""Every Dhanam URL this service builds, pinned as a literal string.

Dhanam serves its whole API under ``/v1`` while ``DHANAM_API_URL`` is a bare
origin, so the version segment is ours to add. It was missing from the billing
client and from the portal route, and no test noticed: the checkout tests all
patched ``DhanamClient.create_checkout`` itself, so no test ever built a URL.

These go the other way round — the client is real and only the transport is
mocked, so what gets asserted is the exact string that would go on the wire.

The checkout tests additionally pin the METHOD, PAYLOAD SHAPE, and AUTH
HEADER SOURCE: checkout previously POSTed to a GET-only Dhanam route while
authenticating with the webhook secret, and neither mistake could fail a
suite that never inspected the outbound request.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from nexus_api.billing_client import DhanamClient, get_billing_status
from nexus_api.config import Settings
from nexus_api.services.checkout_tiers import reset_catalog_cache

# Captured before any patching so the injecting factory below can still build
# a genuine client.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

_DHANAM_URL = "https://api.dhan.am"
_FEDERATION_TOKEN = "fed-token-123"
_WEBHOOK_SECRET = "test-secret"

_CATALOG_BODY = {
    "slug": "selva",
    "tiers": [
        {"tierSlug": "developer", "slug": "developer"},
        {"tierSlug": "team", "slug": "team"},
        {"tierSlug": "business", "slug": "business"},
    ],
}


def _settings_with_dhanam(url: str = _DHANAM_URL) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_api_url=url,
        dhanam_webhook_secret=_WEBHOOK_SECRET,
        federation_api_token=_FEDERATION_TOKEN,
        public_app_url="https://app.selva.town",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(autouse=True)
def _fresh_tier_cache() -> Generator[None, None, None]:
    """The checkout-tier catalog cache is module-global; isolate every test."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()


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

    @property
    def request(self) -> httpx.Request:
        """The single request sent, asserting there was exactly one."""
        assert len(self.requests) == 1, f"expected 1 outbound request, got {len(self.requests)}"
        return self.requests[0]


class _RouteRecorder(_Recorder):
    """A recorder that answers per-path — for flows that make several Dhanam
    calls (catalog → resolve → checkout). Unmapped paths get a 404, which is
    exactly what a wrong URL earns in production."""

    def __init__(self, routes: dict[str, tuple[int, dict[str, Any]]]) -> None:
        super().__init__()
        self._routes = routes

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, body = self._routes.get(
            request.url.path, (404, {"message": f"Cannot {request.method} {request.url.path}"})
        )
        return httpx.Response(status_code, json=body)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def _async_client_factory(recorder: _Recorder) -> Callable[..., httpx.AsyncClient]:
    """Build a drop-in for ``httpx.AsyncClient`` that routes to ``recorder``."""
    transport = httpx.MockTransport(recorder)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    return factory


def _intercept(recorder: _Recorder) -> Any:
    return patch("httpx.AsyncClient", _async_client_factory(recorder))


def _federation_routes(
    *,
    resolve: tuple[int, dict[str, Any]] | None = None,
    checkout: tuple[int, dict[str, Any]] | None = None,
) -> _RouteRecorder:
    """The three-step federated checkout flow with overridable step outcomes."""
    return _RouteRecorder(
        {
            "/v1/billing/catalog/selva": (200, _CATALOG_BODY),
            "/v1/customers/resolve": resolve or (200, {"externalId": "user_123", "created": False}),
            "/v1/customers/user_123/checkout": checkout
            or (201, {"checkoutUrl": "https://checkout.dhan.am/sess_1", "sessionId": "cs_1"}),
        }
    )


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

    async def test_federation_resolve(self) -> None:
        """Resolve is a POST to /v1/customers/resolve carrying the federation
        token — the payload keys are the ones Dhanam's DTO validates."""
        rec = _Recorder(body={"externalId": "user_123", "created": False})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).resolve_federation_customer(
                _FEDERATION_TOKEN,
                email="ops@selva.town",
                janua_sub="janua|abc",
                name="Ops",
            )
        req = rec.request
        assert str(req.url) == "https://api.dhan.am/v1/customers/resolve"
        assert req.method == "POST"
        assert req.headers["Authorization"] == f"Bearer {_FEDERATION_TOKEN}"
        assert json.loads(req.content) == {
            "email": "ops@selva.town",
            "januaSub": "janua|abc",
            "name": "Ops",
        }

    async def test_federation_resolve_omits_absent_identity_fields(self) -> None:
        """januaSub/name are optional upstream — absent, not null."""
        rec = _Recorder(body={"externalId": "user_123", "created": False})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).resolve_federation_customer(
                _FEDERATION_TOKEN, email="ops@selva.town"
            )
        assert json.loads(rec.request.content) == {"email": "ops@selva.town"}

    async def test_federation_checkout(self) -> None:
        """Checkout is a POST to /v1/customers/{externalId}/checkout. The old
        client POSTed /v1/billing/checkout, which Dhanam declares GET-only —
        the URL, the method, the camelCase payload keys, and the auth header
        source are all pinned here so none of them can silently regress."""
        rec = _Recorder(body={"checkoutUrl": "https://checkout.dhan.am/sess_1", "sessionId": "cs"})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).create_federation_checkout(
                _FEDERATION_TOKEN,
                external_id="user_abc",
                plan_id="selva_team",
                success_url="https://app.selva.town/office",
                cancel_url="https://app.selva.town/pricing",
                metadata={"orgId": "org-1", "source": "selva-office"},
            )
        req = rec.request
        assert str(req.url) == "https://api.dhan.am/v1/customers/user_abc/checkout"
        assert req.method == "POST"
        assert req.headers["Authorization"] == f"Bearer {_FEDERATION_TOKEN}"
        assert json.loads(req.content) == {
            "planId": "selva_team",
            "successUrl": "https://app.selva.town/office",
            "cancelUrl": "https://app.selva.town/pricing",
            "metadata": {"orgId": "org-1", "source": "selva-office"},
        }

    async def test_federation_checkout_quotes_external_id(self) -> None:
        """A hostile/odd external id must not be able to rewrite the path."""
        rec = _Recorder(body={"checkoutUrl": "https://checkout.dhan.am/s", "sessionId": "cs"})
        with _intercept(rec):
            await DhanamClient(_DHANAM_URL).create_federation_checkout(
                _FEDERATION_TOKEN,
                external_id="weird/../id",
                plan_id="selva_team",
                success_url="https://app.selva.town/office",
                cancel_url="https://app.selva.town/pricing",
            )
        assert rec.url == "https://api.dhan.am/v1/customers/weird%2F..%2Fid/checkout"

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
        rec = _Recorder(body={"checkoutUrl": "https://checkout.dhan.am/s", "sessionId": "cs"})
        with _intercept(rec):
            await DhanamClient("https://api.dhan.am/v1/").create_federation_checkout(
                _FEDERATION_TOKEN,
                external_id="user_abc",
                plan_id="selva_developer",
                success_url="https://app.selva.town/office",
                cancel_url="https://app.selva.town/pricing",
            )
        assert rec.url == "https://api.dhan.am/v1/customers/user_abc/checkout"

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

    async def test_checkout_route_dials_catalog_then_resolve_then_checkout(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The full federated flow, URL by URL: tier validation reads the
        public catalog, then the customer is resolved, then checkout is
        created against the returned externalId. Every authenticated call
        carries the federation token — and the webhook secret appears in no
        request anywhere (sending it as the bearer was the old defect)."""
        rec = _federation_routes()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch("nexus_api.config.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://checkout.dhan.am/sess_1"
        assert rec.urls == [
            "https://api.dhan.am/v1/billing/catalog/selva",
            "https://api.dhan.am/v1/customers/resolve",
            "https://api.dhan.am/v1/customers/user_123/checkout",
        ]
        methods = [r.method for r in rec.requests]
        assert methods == ["GET", "POST", "POST"]
        # Auth-header source: federation token on both federation calls.
        for req in rec.requests[1:]:
            assert req.headers["Authorization"] == f"Bearer {_FEDERATION_TOKEN}"
        # The webhook secret is not a credential and must never go upstream.
        for req in rec.requests:
            assert _WEBHOOK_SECRET not in str(req.headers)
            assert _WEBHOOK_SECRET not in req.content.decode("utf-8", errors="replace")
        # The checkout payload names the fully-qualified catalog plan id.
        assert json.loads(rec.requests[2].content)["planId"] == "selva_team"

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

    async def test_resolve_404_is_502_and_logs_the_url(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.ERROR, logger="nexus_api.routers.billing")
        rec = _federation_routes(resolve=(404, {"detail": "Not Found"}))
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch("nexus_api.config.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 502
        # The operator gets the URL...
        assert any(
            "https://api.dhan.am/v1/customers/resolve" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        ), "the attempted Dhanam URL must be logged"
        # ...the caller does not: this route is public.
        assert "api.dhan.am" not in resp.text

    async def test_checkout_step_error_is_502_and_logs_the_url(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.ERROR, logger="nexus_api.routers.billing")
        rec = _federation_routes(checkout=(500, {"detail": "boom"}))
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch("nexus_api.config.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 502
        assert any(
            "https://api.dhan.am/v1/customers/user_123/checkout" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        )

    async def test_5xx_is_502(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        rec = _federation_routes(resolve=(503, {"detail": "upstream down"}))
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch("nexus_api.config.get_settings", return_value=_settings_with_dhanam()),
            _intercept(rec),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 502
