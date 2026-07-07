"""Smoke tests for the extracted inference gateway (RFC 0034 P2)."""

from __future__ import annotations

import httpx
import pytest
from inference_gateway.main import create_app


@pytest.mark.asyncio
async def test_health_responds() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["service"] == "inference-gateway"


def test_mounts_the_same_v1_proxy_routes() -> None:
    """The gateway serves the SAME /v1 endpoints nexus-api does — the whole
    point of a drop-in extraction is that callers only change their base URL."""
    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/v1/chat/completions" in paths
    assert "/v1/embeddings" in paths


def test_is_minimal_not_the_monolith() -> None:
    """Extraction succeeds only if the gateway does NOT drag in the ~180-route
    nexus-api surface — its uptime must be independent of campaign/agent code."""
    app = create_app()
    route_count = len([r for r in app.routes if hasattr(r, "path")])
    assert route_count < 20, f"gateway should be minimal, got {route_count} routes"
