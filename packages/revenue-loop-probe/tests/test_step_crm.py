"""Tests for CrmHotLeadStep.

This stage is representative: the other five probe steps
(drafter, email_send, stripe_webhook, dhanam_billing, phynd_attribution)
follow the same pattern — a POST or GET with bearer auth, JSON response
interpretation, skip-when-env-missing, fail-closed on HTTP >= 400.

We drive the HTTP layer with ``respx`` so tests never touch the network
and failures are inspectable via the mock call log.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from revenue_loop_probe.probe import ProbeContext, StageStatus
from revenue_loop_probe.steps import CrmHotLeadStep


PHYND_URL = "https://phynd.example"


def _ctx(env: dict[str, str] | None = None) -> ProbeContext:
    return ProbeContext(
        dry_run=True,
        env=env or {},
        http=httpx.AsyncClient(timeout=2.0),
    )


@pytest.mark.asyncio
async def test_skips_when_env_missing():
    ctx = _ctx({})  # no PHYND_CRM_API_URL / TOKEN set
    res = await CrmHotLeadStep().run(ctx)
    try:
        assert res.status is StageStatus.SKIPPED
        assert "not set" in (res.detail or "")
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_skips_when_only_one_env_set():
    ctx = _ctx({"PHYND_CRM_API_URL": PHYND_URL})  # TOKEN missing
    res = await CrmHotLeadStep().run(ctx)
    try:
        assert res.status is StageStatus.SKIPPED
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_passes_on_2xx_and_threads_lead_id():
    env = {
        "PHYND_CRM_API_URL": PHYND_URL,
        "PHYND_CRM_PROBE_TOKEN": "probe-token-abc",
    }
    ctx = _ctx(env)
    try:
        with respx.mock(base_url=PHYND_URL) as mock:
            route = mock.post("/v1/probe/leads").respond(
                json={"lead_id": "lead_42", "echo": "ok"}, status_code=200
            )
            res = await CrmHotLeadStep().run(ctx)
            assert route.called
            req = route.calls.last.request
            # Auth header must be bearer token, not the raw value.
            assert req.headers["authorization"] == "Bearer probe-token-abc"
            # Correlation id must be forwarded for traceability.
            assert req.headers["x-probe-correlation-id"] == ctx.correlation_id

        assert res.status is StageStatus.PASSED
        assert res.facts["lead_id"] == "lead_42"
        # Lead id must be threaded through ctx.state for later stages.
        assert ctx.state["lead_id"] == "lead_42"
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_accepts_id_as_alias_for_lead_id():
    # Some CRM dialects return `id` instead of `lead_id`; the step must
    # accept either so we don't false-fail.
    env = {
        "PHYND_CRM_API_URL": PHYND_URL,
        "PHYND_CRM_PROBE_TOKEN": "tok",
    }
    ctx = _ctx(env)
    try:
        with respx.mock(base_url=PHYND_URL) as mock:
            mock.post("/v1/probe/leads").respond(json={"id": "lead_99"}, status_code=201)
            res = await CrmHotLeadStep().run(ctx)
        assert res.status is StageStatus.PASSED
        assert ctx.state["lead_id"] == "lead_99"
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_fails_on_4xx():
    env = {
        "PHYND_CRM_API_URL": PHYND_URL,
        "PHYND_CRM_PROBE_TOKEN": "tok",
    }
    ctx = _ctx(env)
    try:
        with respx.mock(base_url=PHYND_URL) as mock:
            mock.post("/v1/probe/leads").respond(json={"error": "unauthorized"}, status_code=403)
            res = await CrmHotLeadStep().run(ctx)
        assert res.status is StageStatus.FAILED
        assert "403" in (res.detail or "")
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_fails_when_response_missing_lead_id():
    env = {
        "PHYND_CRM_API_URL": PHYND_URL,
        "PHYND_CRM_PROBE_TOKEN": "tok",
    }
    ctx = _ctx(env)
    try:
        with respx.mock(base_url=PHYND_URL) as mock:
            mock.post("/v1/probe/leads").respond(json={"echo": "ok"}, status_code=200)
            res = await CrmHotLeadStep().run(ctx)
        assert res.status is StageStatus.FAILED
        assert "lead_id" in (res.detail or "")
    finally:
        await ctx.http.aclose()


@pytest.mark.asyncio
async def test_fails_on_network_exception():
    env = {
        "PHYND_CRM_API_URL": PHYND_URL,
        "PHYND_CRM_PROBE_TOKEN": "tok",
    }
    ctx = _ctx(env)
    try:
        with respx.mock(base_url=PHYND_URL) as mock:
            mock.post("/v1/probe/leads").mock(side_effect=httpx.ConnectError("boom"))
            res = await CrmHotLeadStep().run(ctx)
        assert res.status is StageStatus.FAILED
        assert "ConnectError" in (res.detail or "") or "boom" in (res.detail or "")
    finally:
        await ctx.http.aclose()
