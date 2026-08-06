"""Thin async HTTP client for the Dhanam billing API."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


def _v1_base(base_url: str) -> str:
    """Return ``base_url`` carrying exactly one ``/v1`` version segment.

    ``DHANAM_API_URL`` is configured as a bare origin (``https://api.dhan.am``)
    while Dhanam serves its whole API under ``/v1``. Spelling the segment out
    at each call site is precisely how it went missing here: every request this
    client made 404'd, and the 404 was then read as "Dhanam has not shipped the
    endpoint yet". Normalising once means a new method cannot reintroduce it.

    A base that already ends in ``/v1`` is left alone so re-pointing the env at
    a versioned URL cannot produce ``/v1/v1``. An empty base stays empty — the
    callers guard on "Dhanam not configured" themselves.
    """
    base = base_url.rstrip("/")
    if not base or base.endswith("/v1"):
        return base
    return f"{base}/v1"


class DhanamClient:
    """Async client for the Dhanam billing API.

    Method docstrings name the path *below* the version segment; the
    constructor appends ``/v1`` to the base, so ``/billing/status`` is
    requested as ``<base>/v1/billing/status``.
    """

    def __init__(self, base_url: str, webhook_secret: str = "") -> None:
        self.base_url = _v1_base(base_url)
        self.webhook_secret = webhook_secret

    async def get_status(self, bearer_token: str) -> dict[str, Any]:
        """GET /billing/status -- subscription status."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/billing/status",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_usage(self, bearer_token: str) -> dict[str, Any]:
        """GET /billing/usage -- current billing period usage."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/billing/usage",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def create_portal_session(self, bearer_token: str) -> dict[str, Any]:
        """POST /billing/portal -- create a self-service billing portal session."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/billing/portal",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def resolve_federation_customer(
        self,
        federation_token: str,
        *,
        email: str,
        janua_sub: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """POST /customers/resolve -- resolve (or provision) the Dhanam billing
        customer for a federated identity.

        The server-to-server checkout path is Dhanam's customer-federation
        surface, authenticated with the shared federation token — NOT the
        webhook secret, which only signs inbound webhook payloads and is never
        valid as an outbound credential. ``email`` is the required identity
        key; ``janua_sub`` (the OIDC ``sub`` claim) is the stable
        cross-ecosystem identity and is linked when supplied.

        Returns Dhanam's response, expected to carry the Dhanam user id as
        ``externalId`` — the key ``create_federation_checkout`` requires.
        Raises ``httpx.HTTPStatusError`` on any non-2xx.
        """
        payload: dict[str, Any] = {"email": email}
        if janua_sub:
            payload["januaSub"] = janua_sub
        if name:
            payload["name"] = name
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/customers/resolve",
                headers={"Authorization": f"Bearer {federation_token}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_federation_checkout(
        self,
        federation_token: str,
        *,
        external_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST /customers/{externalId}/checkout -- start a subscription checkout.

        Selva never creates the Stripe object itself (RFC 0011 / the
        monetization-architecture north star: Dhanam is the only holder of
        Stripe keys). This is the federation checkout route — Dhanam declares
        ``/billing/checkout`` GET-only, so the previous POST there could never
        have succeeded (404 "Cannot POST"). The federated flow is: resolve the
        customer's ``externalId`` first, then drive this endpoint with it.

        ``plan_id`` must be the fully-qualified catalog plan id in Dhanam's
        ``{product}_{tier}`` convention (e.g. ``selva_team``) — an unprefixed
        tier slug resolves against the wrong product upstream. ``metadata``
        string pairs are threaded into the PSP session and flow back on the
        payment webhook, which is how the purchase is attributed to the org.

        Returns Dhanam's response, expected to contain ``checkoutUrl`` (and a
        ``sessionId``). Raises ``httpx.HTTPStatusError`` on any non-2xx —
        including 404, which means the request we built was wrong, not that
        Dhanam lacks the feature.
        """
        payload: dict[str, Any] = {
            "planId": plan_id,
            "successUrl": success_url,
            "cancelUrl": cancel_url,
        }
        if metadata:
            payload["metadata"] = metadata
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/customers/{quote(external_id, safe='')}/checkout",
                headers={"Authorization": f"Bearer {federation_token}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_catalog(self, product_slug: str | None = None) -> dict[str, Any]:
        """GET /billing/catalog -- full product catalog or single product (public, no auth)."""
        path = f"/billing/catalog/{product_slug}" if product_slug else "/billing/catalog"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}{path}")
            resp.raise_for_status()
            return resp.json()

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 webhook signature from Dhanam."""
        if not self.webhook_secret:
            logger.warning("No Dhanam webhook secret configured; skipping verification")
            return True
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


async def get_billing_status(dhanam_space_id: str) -> dict[str, Any] | None:
    """Fetch compute token budget from Dhanam for a given space.

    Returns a dict with at least ``compute_tokens_remaining`` on success,
    or ``None`` when the Dhanam API is not configured or unreachable.
    Designed to be called from dispatch-time budget enforcement.
    """
    from .config import get_settings

    settings = get_settings()
    if not settings.dhanam_api_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.dhanam_api_url.rstrip('/')}/v1/spaces/{dhanam_space_id}/budget",
                headers={"Authorization": f"Bearer {settings.dhanam_webhook_secret}"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.debug("Failed to fetch billing status for space %s", dhanam_space_id, exc_info=True)
        return None
