"""Tests for phygital tools."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from selva_tools.builtins import phygital_tools
from selva_tools.builtins.phygital_tools import GenerateQuoteTool


class _RecordingClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "json": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "quoteId": "q_123",
                "totalPrice": 125.5,
                "currency": "MXN",
                "market_context": {"market_verified": True},
            },
        )


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    _RecordingClient.calls = []


class TestGenerateQuoteTool:
    @pytest.mark.asyncio
    async def test_project_slug_uses_yantra_project_quote_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(phygital_tools, "YANTRA4D_API_URL", "https://yantra.test")
        monkeypatch.setattr(phygital_tools, "COTIZA_API_URL", "https://cotiza.test")
        monkeypatch.setattr(phygital_tools.httpx, "AsyncClient", _RecordingClient)

        result = await GenerateQuoteTool().execute(
            project_slug="demo project",
            model_id="m_123",
            require_market_verified=True,
        )

        assert result.success
        assert _RecordingClient.calls == [
            {
                "url": "https://yantra.test/api/projects/demo%20project/cotiza-quote-request",
                "json": {
                    "material": "PLA",
                    "quantity": 1,
                    "process": "fdm",
                    "priority": "standard",
                    "finish": "standard",
                    "currency": "MXN",
                    "notes": "",
                    "require_market_verified": True,
                    "model_id": "m_123",
                },
            }
        ]
        assert "0.00" not in result.output

    @pytest.mark.asyncio
    async def test_without_project_slug_uses_cotiza_structured_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(phygital_tools, "YANTRA4D_API_URL", "https://yantra.test")
        monkeypatch.setattr(phygital_tools, "COTIZA_API_URL", "https://cotiza.test")
        monkeypatch.setattr(phygital_tools.httpx, "AsyncClient", _RecordingClient)

        result = await GenerateQuoteTool().execute(
            geometry={
                "volume_cm3": 1.2,
                "surface_area_cm2": 6.0,
                "bounding_box_mm": {"x": 10, "y": 20, "z": 30},
            },
            project={"name": "Bracket", "units": "mm"},
            require_market_verified=False,
        )

        assert result.success
        assert _RecordingClient.calls == [
            {
                "url": "https://cotiza.test/api/v1/quotes/from-yantra4d",
                "json": {
                    "source": "yantra4d",
                    "geometry": {
                        "volume_cm3": 1.2,
                        "surface_area_cm2": 6.0,
                        "bounding_box_mm": {"x": 10, "y": 20, "z": 30},
                    },
                    "project": {"name": "Bracket", "units": "mm"},
                    "item": {
                        "name": "Bracket",
                        "process": "3d_fff",
                        "material": "PLA",
                        "quantity": 1,
                        "finish": "standard",
                        "options": {
                            "priority": "standard",
                            "require_market_verified": False,
                        },
                    },
                    "currency": "MXN",
                    "notes": "",
                    "require_market_verified": False,
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_cotiza_requires_structured_geometry_and_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(phygital_tools, "COTIZA_API_URL", "https://cotiza.test")
        monkeypatch.setattr(phygital_tools.httpx, "AsyncClient", _RecordingClient)

        result = await GenerateQuoteTool().execute(model_id="m_123")

        assert not result.success
        assert "geometry is required" in (result.error or "")
        assert _RecordingClient.calls == []
