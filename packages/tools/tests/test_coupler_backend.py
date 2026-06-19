"""Tests for CouplerToolBackend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_tools.backends.coupler import (
    CouplerProxyTool,
    CouplerToolBackend,
    coupler_enabled,
)


@pytest.mark.asyncio
async def test_list_tools():
    backend = CouplerToolBackend(base_url="http://coupler.test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "tools": [{"name": "coupler.github.list_repos", "description": "x", "connector": "github"}]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        tools = await backend.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "coupler.github.list_repos"


@pytest.mark.asyncio
async def test_execute_dry_run():
    backend = CouplerToolBackend(base_url="http://coupler.test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"dry_run": True, "tool": "coupler.slack.post_message"}
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = await backend.execute_tool(
            "coupler.slack.post_message",
            {"channel": "#general", "text": "hi"},
            user_jwt="test-jwt",
            dry_run=True,
        )
        assert result["dry_run"] is True


@pytest.mark.asyncio
async def test_proxy_tool_requires_jwt_for_live_execute():
    backend = CouplerToolBackend(base_url="http://coupler.test")
    tool = CouplerProxyTool(
        backend,
        {"name": "coupler.github.list_repos", "description": "list", "parameters": {"type": "object"}},
    )
    result = await tool.execute()
    assert result.success is False
    assert result.error == "user_jwt_required"


def test_coupler_enabled_false_by_default(monkeypatch):
    monkeypatch.delenv("SELVA_COUPLER_TOOLS_ENABLED", raising=False)
    assert coupler_enabled() is False


def test_coupler_enabled_true(monkeypatch):
    monkeypatch.setenv("SELVA_COUPLER_TOOLS_ENABLED", "true")
    assert coupler_enabled() is True
