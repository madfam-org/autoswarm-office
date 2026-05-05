"""Smoke tests for the FastAPI introspection router."""

from __future__ import annotations

import pytest

from madfam_budget_gate import BudgetGate, BudgetScope, build_router


@pytest.mark.asyncio
async def test_health_endpoint(gate: BudgetGate) -> None:
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")

    app = fastapi.FastAPI()
    app.include_router(build_router(gate))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/budget-gate/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["redis_ok"] is True
    assert "default_caps" in body


@pytest.mark.asyncio
async def test_status_endpoint_returns_zeroed_for_fresh_scope(gate: BudgetGate) -> None:
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")

    app = fastapi.FastAPI()
    app.include_router(build_router(gate))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/budget-gate/status", params={"org_id": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"]["org_id"] == "acme"
    assert body["daily"]["used_usd"] == 0.0
    assert body["daily"]["cap_usd"] == 10.0  # env default from fixture


@pytest.mark.asyncio
async def test_cap_endpoint_404_when_no_override(gate: BudgetGate) -> None:
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")

    app = fastapi.FastAPI()
    app.include_router(build_router(gate))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/budget-gate/cap", params={"org_id": "ghost"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cap_endpoint_returns_override(gate: BudgetGate) -> None:
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")

    await gate.set_cap(BudgetScope(org_id="acme"), daily_usd=2.0, monthly_usd=50.0)

    app = fastapi.FastAPI()
    app.include_router(build_router(gate))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/budget-gate/cap", params={"org_id": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["daily_usd"] == 2.0
    assert body["monthly_usd"] == 50.0
