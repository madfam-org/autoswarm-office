"""Thin async HTTP client for the Dhanam billing API."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DhanamClient:
    """Async client for the Dhanam billing API."""

    def __init__(self, base_url: str, webhook_secret: str = "") -> None:
        self.base_url = base_url.rstrip("/")
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

    async def create_checkout(
        self,
        bearer_token: str,
        *,
        tier: str,
        success_url: str,
        cancel_url: str,
        space_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /billing/checkout -- start a subscription checkout.

        Selva never creates the Stripe object itself (RFC 0011 / the
        monetization-architecture north star: Dhanam is the only holder of
        Stripe keys). We hand Dhanam the tier + return URLs; Dhanam creates
        the Stripe Checkout Session / PaymentIntent, and the resulting
        ``subscription.created`` webhook flows back through
        ``handle_dhanam_billing_event``.

        Returns Dhanam's response, expected to contain a hosted-checkout
        ``url`` the caller redirects the browser to. Raises on HTTP error
        (including 404 while Dhanam's checkout endpoint is not yet live).
        """
        payload: dict[str, Any] = {
            "tier": tier,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if space_id:
            payload["space_id"] = space_id
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/billing/checkout",
                headers={"Authorization": f"Bearer {bearer_token}"},
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
