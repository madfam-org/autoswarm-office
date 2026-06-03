"""Tests for Grafana dashboard + panel tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_tools.builtins.grafana import (
    GrafanaDashboardListTool,
    GrafanaPanelExportTool,
    get_grafana_tools,
)


class TestRegistry:
    def test_two_tools_exported(self) -> None:
        names = {t.name for t in get_grafana_tools()}
        assert names == {"grafana_dashboard_list", "grafana_panel_export"}

    def test_schemas_valid(self) -> None:
        for t in get_grafana_tools():
            s = t.parameters_schema()
            assert s["type"] == "object"


# -- credential absence ------------------------------------------------------


class TestCreds:
    @pytest.mark.asyncio
    async def test_list_without_url_returns_error(self) -> None:
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", ""),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
        ):
            r = await GrafanaDashboardListTool().execute()
            assert r.success is False
            assert "GRAFANA_URL" in (r.error or "")

    @pytest.mark.asyncio
    async def test_export_without_token_returns_error(self) -> None:
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", ""),
        ):
            r = await GrafanaPanelExportTool().execute(
                dashboard_uid="abc", panel_id=1, from_time="now-1h"
            )
            assert r.success is False
            assert "GRAFANA_API_TOKEN" in (r.error or "")


# -- dashboard list ---------------------------------------------------------


class TestDashboardList:
    @pytest.mark.asyncio
    async def test_list_returns_compact_projection(self) -> None:
        body = [
            {
                "id": 1,
                "uid": "abc",
                "title": "Selva Overview",
                "url": "/d/abc/overview",
                "tags": ["selva", "prod"],
                "folderId": 0,
                "folderTitle": "General",
            },
            {
                "id": 2,
                "uid": "xyz",
                "title": "Fortuna Errors",
                "url": "/d/xyz/errors",
                "tags": ["fortuna"],
                "folderId": 1,
                "folderTitle": "Fortuna",
            },
        ]
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.grafana._json_request",
                new=AsyncMock(return_value=(200, body)),
            ),
        ):
            r = await GrafanaDashboardListTool().execute(query="selva")
            assert r.success is True
            assert len(r.data["dashboards"]) == 2
            assert r.data["dashboards"][0]["uid"] == "abc"

    @pytest.mark.asyncio
    async def test_list_error(self) -> None:
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.grafana._json_request",
                new=AsyncMock(return_value=(401, {"message": "invalid token"})),
            ),
        ):
            r = await GrafanaDashboardListTool().execute()
            assert r.success is False
            assert "invalid token" in (r.error or "")


# -- panel export ------------------------------------------------------------


def _mock_async_client_with_response(status_code: int, content: bytes, content_type: str):
    """Build a patcher for httpx.AsyncClient that returns a synthetic response."""
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = {"content-type": content_type}

    client_instance = MagicMock()
    client_instance.get = AsyncMock(return_value=response)
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)

    cm_factory = MagicMock(return_value=client_instance)
    return cm_factory


class TestPanelExport:
    @pytest.mark.asyncio
    async def test_successful_png_returns_base64(self) -> None:
        # Minimal 1x1 PNG bytes (just a sentinel — we don't decode it).
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        factory = _mock_async_client_with_response(200, png_bytes, "image/png")
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
            patch("selva_tools.builtins.grafana.httpx.AsyncClient", factory),
        ):
            r = await GrafanaPanelExportTool().execute(
                dashboard_uid="abc",
                panel_id=7,
                from_time="now-1h",
            )
            assert r.success is True
            assert r.data["image_base64"] is not None
            assert r.data["bytes"] == len(png_bytes)
            assert "/d-solo/abc?panelId=7" in r.data["snapshot_url"]

    @pytest.mark.asyncio
    async def test_renderer_unavailable_falls_back_to_url(self) -> None:
        factory = _mock_async_client_with_response(500, b"renderer not installed", "text/plain")
        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
            patch("selva_tools.builtins.grafana.httpx.AsyncClient", factory),
        ):
            r = await GrafanaPanelExportTool().execute(
                dashboard_uid="abc",
                panel_id=7,
                from_time="now-1h",
            )
            # Graceful fallback — still success=True but image_base64 is None.
            assert r.success is True
            assert r.data["image_base64"] is None
            assert "snapshot_url" in r.data
            assert "render_error" in r.data

    @pytest.mark.asyncio
    async def test_network_exception_returns_error(self) -> None:
        async def explode(*args, **kwargs):
            raise ConnectionError("boom")

        client_instance = MagicMock()
        client_instance.get = explode
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=client_instance)

        with (
            patch("selva_tools.builtins.grafana.GRAFANA_URL", "https://g.x"),
            patch("selva_tools.builtins.grafana.GRAFANA_API_TOKEN", "tok"),
            patch("selva_tools.builtins.grafana.httpx.AsyncClient", factory),
        ):
            r = await GrafanaPanelExportTool().execute(
                dashboard_uid="abc",
                panel_id=7,
                from_time="now-1h",
            )
            assert r.success is False
            assert "boom" in (r.error or "")
