"""The root Prometheus /metrics endpoint must not be publicly scrapable.

It enumerates the entire internal API surface (route paths, methods, error
rates) — reconnaissance for an attacker. Prometheus scrapes in-cluster over
the ClusterIP (no Cloudflare edge headers), so those pass; a request bearing
the tunnel's CF headers is public and is refused unless it carries the
service token.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from nexus_api.config import Settings


@pytest.mark.asyncio
class TestMetricsGuard:
    async def test_in_cluster_scrape_allowed(self, client: httpx.AsyncClient) -> None:
        """No Cloudflare headers = in-cluster ClusterIP scrape → allowed."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "python_info" in resp.text or "http_requests_total" in resp.text

    async def test_public_via_cloudflare_blocked(self, client: httpx.AsyncClient) -> None:
        """A request carrying the tunnel's edge header is public → 404."""
        resp = await client.get("/metrics", headers={"cf-connecting-ip": "203.0.113.7"})
        assert resp.status_code == 404
        # cf-ray alone also trips the guard.
        resp2 = await client.get("/metrics", headers={"cf-ray": "abc123-DFW"})
        assert resp2.status_code == 404

    async def test_public_with_service_token_allowed(
        self, client: httpx.AsyncClient
    ) -> None:
        """A public request presenting the service token is allowed (external
        Prometheus federation still works)."""
        patched = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            worker_api_token="real-scrape-token",
            _env_file=None,  # type: ignore[call-arg]
        )
        with patch("nexus_api.main.get_settings", return_value=patched):
            resp = await client.get(
                "/metrics",
                headers={
                    "cf-connecting-ip": "203.0.113.7",
                    "authorization": "Bearer real-scrape-token",
                },
            )
        assert resp.status_code == 200

    async def test_public_with_wrong_token_blocked(
        self, client: httpx.AsyncClient
    ) -> None:
        patched = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            worker_api_token="real-scrape-token",
            _env_file=None,  # type: ignore[call-arg]
        )
        with patch("nexus_api.main.get_settings", return_value=patched):
            resp = await client.get(
                "/metrics",
                headers={
                    "cf-connecting-ip": "203.0.113.7",
                    "authorization": "Bearer wrong",
                },
            )
        assert resp.status_code == 404
