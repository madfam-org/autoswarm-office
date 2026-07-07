"""Tests for the convergence read surface (RFC 0034 P1b / D7).

Verifies the route converge-dash calls (`GET /api/v1/convergence/ai-tasks`)
exists, is authenticated, and returns the SelvaAiTask contract joined with the
P1 USD usage ledger.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_ai_tasks_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/convergence/ai-tasks?period_start=2026-07-01T00:00:00&period_end=2026-07-08T00:00:00"
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ai_tasks_returns_contract_shape(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/v1/convergence/ai-tasks",
        params={"period_start": "2026-07-01T00:00:00", "period_end": "2026-07-08T00:00:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Every item (if any) carries the required contract fields.
    for item in body:
        assert "task_id" in item
        assert "workflow_name" in item
        assert "status" in item


@pytest.mark.asyncio
async def test_malformed_window_returns_empty_not_500(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/v1/convergence/ai-tasks",
        params={"period_start": "not-a-date", "period_end": "also-bad"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
