"""Tests for Loki log-query tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from selva_tools.builtins.loki import (
    LokiLabelsTool,
    LokiQueryRangeTool,
    get_loki_tools,
)


class TestRegistry:
    def test_two_tools_exported(self) -> None:
        names = {t.name for t in get_loki_tools()}
        assert names == {"loki_query_range", "loki_labels"}

    def test_schemas_valid(self) -> None:
        for t in get_loki_tools():
            s = t.parameters_schema()
            assert s["type"] == "object"


# -- loki_query_range -------------------------------------------------------


class TestLokiQueryRange:
    @pytest.mark.asyncio
    async def test_query_flattens_streams(self) -> None:
        body = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"namespace": "selva", "pod": "nexus-api-a"},
                        "values": [
                            ["1700000000000000000", "line one"],
                            ["1700000000500000000", "line two"],
                        ],
                    },
                    {
                        "stream": {"namespace": "selva", "pod": "workers-b"},
                        "values": [
                            ["1700000001000000000", "worker tick"],
                        ],
                    },
                ],
            },
        }
        with patch(
            "selva_tools.builtins.loki._loki_request",
            new=AsyncMock(return_value=(200, body)),
        ):
            r = await LokiQueryRangeTool().execute(
                query='{namespace="selva"}',
                start="1700000000000000000",
                end="1700000002000000000",
            )
            assert r.success is True
            assert r.data["stream_count"] == 2
            assert r.data["line_count"] == 3
            assert r.data["streams"][0]["entries"][0]["line"] == "line one"

    @pytest.mark.asyncio
    async def test_error_bubbles_up(self) -> None:
        with patch(
            "selva_tools.builtins.loki._loki_request",
            new=AsyncMock(return_value=(400, {"status": "error", "message": "parse error"})),
        ):
            r = await LokiQueryRangeTool().execute(query="bad{query", start="0", end="1")
            assert r.success is False
            assert "parse error" in (r.error or "")


# -- loki_labels ------------------------------------------------------------


class TestLokiLabels:
    @pytest.mark.asyncio
    async def test_labels_returns_list(self) -> None:
        body = {
            "status": "success",
            "data": ["namespace", "pod", "container", "app", "level"],
        }
        with patch(
            "selva_tools.builtins.loki._loki_request",
            new=AsyncMock(return_value=(200, body)),
        ):
            r = await LokiLabelsTool().execute()
            assert r.success is True
            assert "namespace" in r.data["labels"]
            assert len(r.data["labels"]) == 5

    @pytest.mark.asyncio
    async def test_labels_5xx_returns_error(self) -> None:
        with patch(
            "selva_tools.builtins.loki._loki_request",
            new=AsyncMock(return_value=(503, "upstream timeout")),
        ):
            r = await LokiLabelsTool().execute()
            assert r.success is False
