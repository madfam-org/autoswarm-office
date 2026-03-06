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
