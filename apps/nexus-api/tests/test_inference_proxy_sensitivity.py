"""The gateway's data-handling contract, enforced.

Four properties are asserted here, each of which was a real defect or a
real unverified claim before this suite:

1. ``X-Sensitivity`` fails CLOSED. Absent or invalid ⇒ 400. It used to
   default to ``public`` — and an invalid value was swallowed by a
   ``contextlib.suppress(ValueError)``, so a typo silently downgraded a
   clinical request to "cheapest cloud vendor" with no log line at all.
2. A tenant's server-side sensitivity FLOOR holds even when the client
   under-declares, so a dropped header at any hop cannot degrade a
   regulated tenant.
3. There is a server-side deadline. Without it the worst case for a
   restricted call was ~601 s (300 s Ollama timeout, retry, 300 s again)
   with a human waiting on the other end.
4. Neither prompts nor completions are persisted or logged. The audit
   found this to be true by inspection; these tests make it a regression
   gate rather than a claim.

The tests drive a minimal FastAPI app mounting the real router with the
real auth dependency overridden — the point is the proxy's own logic, not
the JWT layer.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from madfam_inference.tenant_policy import (
    TenantPolicy,
    TenantPolicyBook,
    load_tenant_policies,
)
from madfam_inference.types import InferenceResponse, Sensitivity
from nexus_api.auth import get_current_user
from nexus_api.database import get_db
from nexus_api.routers import inference_proxy

CREA_ORG_ID = "e6cbd51d-8329-4c4e-8c74-aba643ab4575"

# Stand-in for a clinical note. Never a real one, and the assertions below
# are exactly that this string does not escape into a log or a ledger.
CLINICAL_TEXT = "El menor J.P. mostró conducta disruptiva durante la sesión del martes."


class _FakeRouter:
    """Records what it was asked to route, and answers instantly."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.seen: list[Any] = []

    async def complete(self, request):
        self.seen.append(request)
        if self.raises is not None:
            raise self.raises
        return InferenceResponse(
            content="Resumen sugerido.",
            model="llama3.1:8b-instruct-q4_K_M",
            provider="ollama",
            usage={"input_tokens": 40, "output_tokens": 12},
        )


class _FakeReqShim:
    """Minimal stand-in for an InferenceRequest in the streaming path —
    _stream_chunks only reads `policy.model_override`."""

    class _Policy:
        model_override = None

    policy = _Policy()


def _build_app(org_id: str = "platform") -> FastAPI:
    app = FastAPI()
    app.include_router(inference_proxy.router, prefix="/v1")

    async def _fake_user() -> dict[str, Any]:
        return {
            "sub": "service:worker",
            "roles": ["service", "worker"],
            "org_id": org_id,
            "email": "worker@selva.internal",
        }

    async def _fake_db():
        yield None

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = _fake_db
    return app


async def _post(app: FastAPI, headers: dict[str, str], **body_overrides):
    body = {
        "model": "auto",
        "messages": [{"role": "user", "content": CLINICAL_TEXT}],
        **body_overrides,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.post("/v1/chat/completions", json=body, headers=headers)


@pytest.fixture(autouse=True)
def _no_side_effects():
    """Neutralise the ledger and the event emitter; both are exercised by
    their own suites and neither is the subject here."""
    load_tenant_policies.cache_clear()
    with (
        patch.object(inference_proxy, "_record_usage", new=AsyncMock()),
        patch.object(inference_proxy, "_emit_proxy_event"),
    ):
        yield
    load_tenant_policies.cache_clear()
    inference_proxy._rate_limiter = None


@pytest.fixture()
def fake_router():
    router = _FakeRouter()
    with patch.object(inference_proxy, "_get_router", return_value=router):
        yield router


def _policies(book: TenantPolicyBook):
    return patch.object(inference_proxy, "_get_tenant_policies", return_value=book)


# ---------------------------------------------------------------------------
# 1. Fail closed on sensitivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSensitivityFailsClosed:
    async def test_missing_header_is_400(self, fake_router: _FakeRouter) -> None:
        resp = await _post(_build_app(), {"Authorization": "Bearer t"})
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert error["code"] == "missing_sensitivity"
        # The error must teach the caller the valid values.
        for level in Sensitivity:
            assert level.value in error["message"]

    async def test_missing_header_never_reaches_a_provider(
        self, fake_router: _FakeRouter
    ) -> None:
        """The load-bearing assertion: a header-less request must not be
        routed anywhere at all, least of all to the cheapest cloud vendor."""
        await _post(_build_app(), {"Authorization": "Bearer t"})
        assert fake_router.seen == []

    @pytest.mark.parametrize(
        "value",
        ["publik", "PUBLIC-ISH", "restrictedd", "confident", "0", "null", "public;internal"],
    )
    async def test_invalid_value_is_400(self, fake_router: _FakeRouter, value: str) -> None:
        resp = await _post(
            _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": value}
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] in (
            "invalid_sensitivity",
            "missing_sensitivity",
        )
        assert fake_router.seen == []

    @pytest.mark.parametrize("level", [s.value for s in Sensitivity])
    async def test_every_valid_level_is_accepted(
        self, fake_router: _FakeRouter, level: str
    ) -> None:
        resp = await _post(
            _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": level}
        )
        assert resp.status_code == 200
        assert fake_router.seen[-1].policy.sensitivity.value == level

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    async def test_blank_header_is_treated_as_absent(
        self, fake_router: _FakeRouter, value: str
    ) -> None:
        """A header present but empty is a missing declaration, not a
        malformed one — either way it is a 400 and nothing is routed."""
        resp = await _post(
            _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": value}
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_sensitivity"
        assert fake_router.seen == []

    @pytest.mark.parametrize(
        "level", ["RESTRICTED", "Restricted", "rEsTrIcTeD", " restricted ", "restricted\n"]
    )
    async def test_casing_and_padding_are_tolerated(
        self, fake_router: _FakeRouter, level: str
    ) -> None:
        """Case- and whitespace-insensitivity is deliberate. Neither is a
        downgrade risk (the value still has to name a real level), and
        rejecting `Restricted` would fail closed for the wrong reason."""
        resp = await _post(
            _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": level}
        )
        assert resp.status_code == 200
        assert fake_router.seen[-1].policy.sensitivity is Sensitivity.RESTRICTED

    async def test_rejection_is_logged_without_prompt_text(
        self, fake_router: _FakeRouter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The rejection must be visible to operators AND must not put the
        clinical payload into the log stream."""
        with caplog.at_level(logging.WARNING, logger=inference_proxy.logger.name):
            await _post(_build_app(org_id=CREA_ORG_ID), {"Authorization": "Bearer t"})

        records = [r for r in caplog.records if "X-Sensitivity" in r.getMessage()]
        assert records, "the rejection must produce a WARNING"
        combined = " ".join(r.getMessage() for r in caplog.records)
        assert CLINICAL_TEXT not in combined
        assert "menor" not in combined
        assert CREA_ORG_ID in combined  # org is routing metadata, not content

    async def test_invalid_value_rejection_is_logged(
        self, fake_router: _FakeRouter, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=inference_proxy.logger.name):
            await _post(
                _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": "publik"}
            )
        combined = " ".join(r.getMessage() for r in caplog.records)
        assert "publik" in combined
        assert CLINICAL_TEXT not in combined


# ---------------------------------------------------------------------------
# 2. Tenant floor and tenant limits
# ---------------------------------------------------------------------------


def _crea_book(**overrides) -> TenantPolicyBook:
    """The shipped CTM policy, with per-test overrides."""
    fields: dict[str, Any] = {
        "org_id": CREA_ORG_ID,
        "display_name": "Crea Tu Mundo",
        "sensitivity_floor": Sensitivity.RESTRICTED,
        "allowed_task_types": ["summarization", "family-feedback"],
        "max_tokens_cap": 1500,
        "request_timeout_seconds": 40.0,
        "rate_limit_per_minute": 30,
        "daily_usd_budget": 2.0,
    }
    fields.update(overrides)
    return TenantPolicyBook(tenants={CREA_ORG_ID: TenantPolicy(**fields)})


@pytest.mark.asyncio
class TestTenantFloor:
    @pytest.mark.parametrize("declared", ["public", "internal"])
    async def test_under_declared_request_is_raised_to_the_floor(
        self, fake_router: _FakeRouter, declared: str
    ) -> None:
        """If the MAP's header is ever dropped or rewritten by a hop, the
        gateway still treats CTM's data as restricted."""
        with _policies(_crea_book()):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": declared},
            )
        assert resp.status_code == 200
        assert fake_router.seen[-1].policy.sensitivity is Sensitivity.RESTRICTED

    async def test_floor_never_lowers_a_stricter_request(
        self, fake_router: _FakeRouter
    ) -> None:
        with _policies(_crea_book(sensitivity_floor=Sensitivity.INTERNAL)):
            await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )
        assert fake_router.seen[-1].policy.sensitivity is Sensitivity.RESTRICTED

    async def test_other_tenants_are_unaffected(self, fake_router: _FakeRouter) -> None:
        """The policy book only ever tightens the tenant it names."""
        with _policies(_crea_book()):
            await _post(
                _build_app(org_id="dhanam"),
                {"Authorization": "Bearer t", "X-Sensitivity": "public"},
            )
        assert fake_router.seen[-1].policy.sensitivity is Sensitivity.PUBLIC

    async def test_floor_still_requires_the_header(self, fake_router: _FakeRouter) -> None:
        """A floor is a safety net, not a licence to omit the declaration —
        the header stays mandatory even for a tenant with a floor."""
        with _policies(_crea_book()):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID), {"Authorization": "Bearer t"}
            )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestTenantLimits:
    @pytest.mark.parametrize("task_type", ["summarization", "family-feedback"])
    async def test_map_task_types_are_allowed(
        self, fake_router: _FakeRouter, task_type: str
    ) -> None:
        with _policies(_crea_book()):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {
                    "Authorization": "Bearer t",
                    "X-Sensitivity": "restricted",
                    "X-Task-Type": task_type,
                },
            )
        assert resp.status_code == 200

    async def test_unlisted_task_type_is_rejected(self, fake_router: _FakeRouter) -> None:
        """A new AI surface must be added to the tenant policy deliberately,
        not appear by sending a new header value."""
        with _policies(_crea_book()):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {
                    "Authorization": "Bearer t",
                    "X-Sensitivity": "restricted",
                    "X-Task-Type": "coding",
                },
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "task_type_not_allowed"
        assert fake_router.seen == []

    async def test_max_tokens_is_capped_by_tenant_policy(
        self, fake_router: _FakeRouter
    ) -> None:
        with _policies(_crea_book()):
            await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
                max_tokens=32000,
            )
        assert fake_router.seen[-1].policy.max_tokens == 1500

    async def test_gateway_default_cap_applies_without_a_tenant_policy(
        self, fake_router: _FakeRouter
    ) -> None:
        with _policies(TenantPolicyBook(default_max_tokens_cap=4096)):
            await _post(
                _build_app(),
                {"Authorization": "Bearer t", "X-Sensitivity": "public"},
                max_tokens=32000,
            )
        assert fake_router.seen[-1].policy.max_tokens == 4096

    async def test_rate_limit_denies_past_the_ceiling(
        self, fake_router: _FakeRouter
    ) -> None:
        inference_proxy._rate_limiter = None
        headers = {"Authorization": "Bearer t", "X-Sensitivity": "restricted"}
        app = _build_app(org_id=CREA_ORG_ID)
        with _policies(_crea_book(rate_limit_per_minute=2)):
            assert (await _post(app, headers)).status_code == 200
            assert (await _post(app, headers)).status_code == 200
            limited = await _post(app, headers)

        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "tenant_rate_limited"
        assert int(limited.headers["Retry-After"]) >= 1
        # The denied call never reached a provider.
        assert len(fake_router.seen) == 2

    async def test_tenant_without_a_limit_is_not_rate_limited(
        self, fake_router: _FakeRouter
    ) -> None:
        inference_proxy._rate_limiter = None
        headers = {"Authorization": "Bearer t", "X-Sensitivity": "public"}
        app = _build_app(org_id="dhanam")
        with _policies(_crea_book()):
            for _ in range(50):
                assert (await _post(app, headers)).status_code == 200


# ---------------------------------------------------------------------------
# 3. Deadlines and the fail-closed 503
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeadlinesAndFailClosed:
    async def test_slow_provider_returns_504_not_a_hang(self) -> None:
        import asyncio

        class _SlowRouter:
            async def complete(self, request):
                await asyncio.sleep(30)
                raise AssertionError("should have been cancelled")

        with (
            patch.object(inference_proxy, "_get_router", return_value=_SlowRouter()),
            _policies(TenantPolicyBook(default_request_timeout_seconds=0.05)),
        ):
            resp = await _post(
                _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": "public"}
            )

        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "inference_timeout"

    async def test_tenant_timeout_overrides_the_default(self) -> None:
        """The tenant's own deadline is what gets applied."""
        import asyncio

        seen: dict[str, float] = {}

        class _SlowRouter:
            async def complete(self, request):
                await asyncio.sleep(10)

        book = _crea_book(request_timeout_seconds=0.05)
        with (
            patch.object(inference_proxy, "_get_router", return_value=_SlowRouter()),
            _policies(book),
        ):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )
        seen["status"] = resp.status_code
        assert seen["status"] == 504

    async def test_streaming_stops_at_the_deadline(self) -> None:
        """A stalled stream must not hold the connection for the provider's
        own 300 s timeout. The client gets an error chunk and [DONE], not a
        dangling socket."""
        import asyncio

        class _StallingRouter:
            async def stream(self, request, on_usage=None):
                yield "primer "
                await asyncio.sleep(0.2)
                yield "fragmento"

        chunks = [
            c
            async for c in inference_proxy._stream_chunks(
                _StallingRouter(),
                _FakeReqShim(),
                "cmpl-timeout",
                {"sub": "svc", "org_id": CREA_ORG_ID},
                timeout_seconds=0.05,
            )
        ]
        body = "".join(chunks)
        assert "primer " in body
        assert "inference_timeout" in body
        assert body.rstrip().endswith("data: [DONE]")

    @pytest.mark.parametrize("level", ["restricted", "confidential"])
    async def test_no_local_backend_is_a_named_503(self, level: str) -> None:
        """The audit's finding, preserved and made legible: with no local
        backend a regulated call must 503 with a reason an operator can
        act on — never fall through to a cloud vendor."""
        router = _FakeRouter(raises=RuntimeError("All providers failed for request."))
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            _policies(TenantPolicyBook()),
        ):
            resp = await _post(
                _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": level}
            )

        assert resp.status_code == 503
        error = resp.json()["error"]
        assert error["code"] == "local_backend_unavailable"
        assert "OLLAMA_BASE_URL" in error["message"]
        assert level in error["message"]

    async def test_public_failure_keeps_the_generic_503(self) -> None:
        router = _FakeRouter(raises=RuntimeError("All providers failed for request."))
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            _policies(TenantPolicyBook()),
        ):
            resp = await _post(
                _build_app(), {"Authorization": "Bearer t", "X-Sensitivity": "public"}
            )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "provider_error"


# ---------------------------------------------------------------------------
# 4. No prompt or completion is persisted or logged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoContentPersistence:
    async def test_ledger_receives_counts_only_never_content(self) -> None:
        """The ledger call is inspected argument by argument: token counts,
        provider, model, org and caller — and nothing else."""
        router = _FakeRouter()
        recorded = AsyncMock()
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            patch.object(inference_proxy, "_record_usage", new=recorded),
            patch.object(inference_proxy, "_emit_proxy_event"),
            _policies(_crea_book()),
        ):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )
        assert resp.status_code == 200
        recorded.assert_awaited_once()

        serialized = repr(recorded.await_args.args) + repr(recorded.await_args.kwargs)
        assert CLINICAL_TEXT not in serialized
        assert "Resumen sugerido" not in serialized
        # What IS recorded: counts and routing metadata.
        assert "prompt_tokens" in serialized
        assert "ollama" in serialized

    async def test_usage_ledger_model_has_no_content_column(self) -> None:
        """Structural guarantee, not a behavioural one: there is nowhere in
        the ledger schema for a prompt to be written even by accident."""
        from nexus_api.models import ComputeTokenLedger

        columns = {c.name.lower() for c in ComputeTokenLedger.__table__.columns}
        forbidden = {
            "prompt",
            "prompts",
            "completion",
            "completions",
            "content",
            "messages",
            "message",
            "text",
            "response",
            "request_body",
            "payload",
        }
        assert not (columns & forbidden), f"content-bearing column(s): {columns & forbidden}"

    async def test_successful_call_logs_no_prompt_or_completion(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        router = _FakeRouter()
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            patch.object(inference_proxy, "_record_usage", new=AsyncMock()),
            patch.object(inference_proxy, "_emit_proxy_event"),
            _policies(_crea_book()),
            caplog.at_level(logging.DEBUG),
        ):
            await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )

        combined = " ".join(r.getMessage() for r in caplog.records)
        assert CLINICAL_TEXT not in combined
        assert "Resumen sugerido" not in combined

    async def test_provider_failure_logs_no_prompt(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The audit flagged this as unverified: an exception path must not
        echo the request body into the log stream."""
        router = _FakeRouter(
            raises=RuntimeError("All providers failed for request. Last error: refused")
        )
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            _policies(_crea_book()),
            caplog.at_level(logging.DEBUG),
        ):
            resp = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )

        assert resp.status_code == 503
        combined = " ".join(r.getMessage() for r in caplog.records)
        assert CLINICAL_TEXT not in combined

    async def test_error_bodies_carry_no_prompt(self) -> None:
        """Nor may an error RESPONSE echo the payload back."""
        router = _FakeRouter(raises=RuntimeError("boom"))
        with (
            patch.object(inference_proxy, "_get_router", return_value=router),
            _policies(_crea_book()),
        ):
            failed = await _post(
                _build_app(org_id=CREA_ORG_ID),
                {"Authorization": "Bearer t", "X-Sensitivity": "restricted"},
            )
        rejected = await _post(_build_app(org_id=CREA_ORG_ID), {"Authorization": "Bearer t"})

        for resp in (failed, rejected):
            assert CLINICAL_TEXT not in resp.text
