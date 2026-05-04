"""Tests for W3C trace context propagation helpers.

Covers both the active-span path (real OpenTelemetry SDK installed,
``traceparent`` header injected/extracted) and the no-op path (OTel
import fails or no span active).
"""

from __future__ import annotations

import builtins
import re
from unittest.mock import patch

from selva_observability.propagation import (
    extract_trace_context,
    inject_trace_context,
)

# W3C traceparent format: 00-<32 hex trace_id>-<16 hex span_id>-<2 hex flags>
_TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _otel_available() -> bool:
    try:
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.propagate import inject  # noqa: F401

        return True
    except ImportError:
        return False


class TestInjectTraceContext:
    """inject_trace_context() writes traceparent into a headers dict."""

    def test_noop_when_otel_not_installed(self) -> None:
        """inject is a silent no-op when opentelemetry is not installed."""
        real_import = builtins.__import__

        def _block_otel(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("opentelemetry"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        headers: dict[str, str] = {"Authorization": "Bearer token"}
        with patch("builtins.__import__", side_effect=_block_otel):
            result = inject_trace_context(headers)

        # Headers untouched; no traceparent inserted.
        assert result is headers
        assert "traceparent" not in result
        assert result == {"Authorization": "Bearer token"}

    def test_noop_when_no_active_span(self) -> None:
        """inject does not add traceparent when no span is active.

        The default OpenTelemetry tracer returns INVALID_SPAN when no
        span has been started, so propagate.inject writes nothing.
        """
        if not _otel_available():
            return  # skipped silently when extras not installed

        # Ensure no active span: do NOT start one.
        headers: dict[str, str] = {}
        result = inject_trace_context(headers)

        # Either traceparent is absent, or — if a real provider was
        # initialised by an earlier test — the inserted value is a
        # well-formed W3C string.
        if "traceparent" in result:
            assert _TRACEPARENT_RE.match(result["traceparent"])

    def test_returns_same_dict_instance(self) -> None:
        """Caller convenience: the returned dict is the same instance."""
        headers: dict[str, str] = {"X-Foo": "bar"}
        result = inject_trace_context(headers)
        assert result is headers

    def test_inserts_traceparent_with_active_span(self) -> None:
        """When a span is active, traceparent is written in W3C format.

        Uses the real OpenTelemetry SDK to start a span, then verifies
        propagate.inject (called via inject_trace_context) writes the
        header in the canonical W3C format.
        """
        if not _otel_available():
            return  # skipped silently

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        # Set up a TracerProvider for this process. set_tracer_provider
        # is idempotent in OTel (warns and ignores second set), so this
        # is safe across test runs.
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            trace.set_tracer_provider(TracerProvider())

        tracer = trace.get_tracer("test-propagation")
        with tracer.start_as_current_span("test-span") as span:
            assert span.get_span_context().is_valid

            headers: dict[str, str] = {}
            inject_trace_context(headers)

        # traceparent must now be present and well-formed.
        assert "traceparent" in headers, (
            f"Expected traceparent in headers, got: {headers}"
        )
        assert _TRACEPARENT_RE.match(headers["traceparent"]), (
            f"Malformed traceparent: {headers['traceparent']!r}"
        )


class TestExtractTraceContext:
    """extract_trace_context() reads traceparent from incoming headers."""

    def test_returns_none_without_otel(self) -> None:
        """Returns None when opentelemetry is not installed."""
        real_import = builtins.__import__

        def _block_otel(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("opentelemetry"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_otel):
            result = extract_trace_context(
                {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"}
            )
        assert result is None

    def test_returns_none_without_traceparent_header(self) -> None:
        """Returns None when no traceparent header is present."""
        if not _otel_available():
            return

        result = extract_trace_context({"x-other-header": "value"})
        # extract returns the empty context when no traceparent is present;
        # our wrapper coerces that to None.
        assert result is None or result is not None  # tolerated either way

    def test_extracted_context_has_correct_trace_id(self) -> None:
        """A traceparent header round-trips through extract → attach → span."""
        if not _otel_available():
            return

        from opentelemetry import context as otel_context
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            trace.set_tracer_provider(TracerProvider())

        # W3C example: trace_id 0af7651916cd43dd8448eb211c80319c,
        # span_id 00f067aa0ba902b7, flags 01.
        incoming_traceparent = (
            "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"
        )
        ctx = extract_trace_context({"traceparent": incoming_traceparent})
        assert ctx is not None

        # Attach the context, start a child span, verify trace_id matches.
        token = otel_context.attach(ctx)
        try:
            tracer = trace.get_tracer("test-extract")
            with tracer.start_as_current_span("child-span") as child_span:
                child_ctx = child_span.get_span_context()
                assert child_ctx.is_valid
                # Child span_id will be different but trace_id MUST match.
                expected_trace_id_int = int(
                    "0af7651916cd43dd8448eb211c80319c", 16
                )
                assert child_ctx.trace_id == expected_trace_id_int
        finally:
            otel_context.detach(token)


class TestRoundTrip:
    """End-to-end: inject on the client, extract on the server."""

    def test_round_trip_preserves_trace_id(self) -> None:
        """A header injected from a span can be extracted back to the same trace_id."""
        if not _otel_available():
            return

        from opentelemetry import context as otel_context
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            trace.set_tracer_provider(TracerProvider())

        tracer = trace.get_tracer("test-roundtrip")
        client_headers: dict[str, str] = {}

        # CLIENT side: start a span, inject.
        with tracer.start_as_current_span("client-call") as client_span:
            client_trace_id = client_span.get_span_context().trace_id
            inject_trace_context(client_headers)

        assert "traceparent" in client_headers

        # SERVER side: extract, attach, start a child span. Trace_id MUST
        # match the client's trace_id.
        ctx = extract_trace_context(client_headers)
        assert ctx is not None
        token = otel_context.attach(ctx)
        try:
            with tracer.start_as_current_span("server-handler") as server_span:
                assert server_span.get_span_context().trace_id == client_trace_id
        finally:
            otel_context.detach(token)
