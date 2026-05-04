"""Tests for the W3C trace context extraction middleware.

These tests stand a tiny FastAPI app up with the TraceContextMiddleware
mounted (no nexus-api dependency), to keep the test focused on
propagation behaviour rather than the full middleware stack.
"""

from __future__ import annotations

import builtins
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from nexus_api.middleware.tracing import TraceContextMiddleware


def _otel_available() -> bool:
    try:
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.propagate import extract  # noqa: F401

        return True
    except ImportError:
        return False


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with only the trace middleware mounted."""
    app = FastAPI()
    app.add_middleware(TraceContextMiddleware)

    @app.get("/echo-trace")
    async def echo_trace() -> JSONResponse:
        """Return the current span's trace_id as a hex string, or empty."""
        try:
            from opentelemetry import trace
            from opentelemetry.trace import format_trace_id

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                return JSONResponse({"trace_id": format_trace_id(ctx.trace_id)})
        except ImportError:
            pass
        return JSONResponse({"trace_id": ""})

    return app


@pytest.mark.asyncio
async def test_no_header_passes_through() -> None:
    """When no traceparent is sent, the middleware is a no-op."""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/echo-trace")
    assert resp.status_code == 200
    # Either OTel is not installed and trace_id is empty, or no parent
    # context was attached so the handler also has no active span.
    body = resp.json()
    assert "trace_id" in body


@pytest.mark.asyncio
async def test_traceparent_header_extracted_and_attached() -> None:
    """A traceparent header on the request is extracted and inherited.

    Spans created inside the request handler MUST have the same trace_id
    as the incoming traceparent header. This is the core propagation
    contract.
    """
    if not _otel_available():
        pytest.skip("opentelemetry not installed")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # Ensure a real provider is set so spans have valid contexts.
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        trace.set_tracer_provider(TracerProvider())

    # Pin a known trace_id by sending a synthetic traceparent.
    incoming_trace_hex = "0af7651916cd43dd8448eb211c80319c"
    incoming_traceparent = f"00-{incoming_trace_hex}-00f067aa0ba902b7-01"

    app = _make_app()

    # Wrap the handler so it explicitly starts a child span (otherwise
    # there's no active span to inspect — we only attached the parent
    # CONTEXT, not started a span ourselves).
    @app.get("/with-child-span")
    async def with_child_span() -> JSONResponse:
        from opentelemetry import trace as _trace
        from opentelemetry.trace import format_trace_id

        tracer = _trace.get_tracer("test-handler")
        with tracer.start_as_current_span("child") as span:
            return JSONResponse(
                {"trace_id": format_trace_id(span.get_span_context().trace_id)}
            )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/with-child-span",
            headers={"traceparent": incoming_traceparent},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Child span trace_id MUST equal the incoming trace_id.
    assert body["trace_id"] == incoming_trace_hex, (
        f"Expected child span to inherit trace_id {incoming_trace_hex}, "
        f"got {body['trace_id']!r}"
    )


@pytest.mark.asyncio
async def test_middleware_noop_when_otel_missing() -> None:
    """Middleware does not raise when OTel is not importable.

    Simulates a stripped-down install by blocking the
    ``selva_observability`` extract path AND the ``opentelemetry``
    import. The request should still 200.
    """
    real_import = builtins.__import__

    def _block_otel(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    app = _make_app()
    transport = httpx.ASGITransport(app=app)

    # Send a traceparent header so the middleware tries to do work.
    with patch("builtins.__import__", side_effect=_block_otel):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/echo-trace",
                headers={"traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01"},
            )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_malformed_traceparent_does_not_raise() -> None:
    """Garbage in the traceparent header must not 500 the request."""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/echo-trace",
            headers={"traceparent": "this-is-not-a-valid-traceparent"},
        )
    assert resp.status_code == 200
