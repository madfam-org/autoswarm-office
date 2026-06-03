"""Tests for OpenAPI documentation endpoints."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
class TestOpenAPI:
    async def test_openapi_json(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "Selva Nexus API"
        assert "/api/v1/chat/history" in data["paths"]

    async def test_docs_page(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()
