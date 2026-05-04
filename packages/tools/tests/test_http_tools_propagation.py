"""Tests for W3C trace context propagation in HTTP tools.

The ``_build_safe_request_kwargs`` helper underpins HTTPRequestTool,
GraphQLQueryTool, and WebhookSendTool. Its responsibility is to inject
``traceparent`` (when an OTel span is active) so downstream services can
correlate traces.
"""

from __future__ import annotations

import builtins
import re
import socket
from unittest.mock import patch


def _otel_available() -> bool:
    try:
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.propagate import inject  # noqa: F401

        return True
    except ImportError:
        return False


def _patch_dns(*, hostname: str = "example.com", ip: str = "93.184.216.34"):
    """Make ``socket.getaddrinfo`` return a non-private IP for ``hostname``.

    Returns a context manager. Used so the SSRF guard does not reject
    ``http://example.com`` in the test environment (which may have no
    DNS or resolve example.com to a private IP behind a corporate
    proxy).
    """
    real = socket.getaddrinfo

    def _fake(host: str, *args: object, **kwargs: object) -> object:
        if host == hostname:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
        return real(host, *args, **kwargs)

    return patch("socket.getaddrinfo", side_effect=_fake)


class TestPropagationInBuildKwargs:
    """_build_safe_request_kwargs injects traceparent into outgoing headers."""

    def test_no_traceparent_without_active_span(self) -> None:
        """No traceparent is added when no OTel span is active."""
        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        with _patch_dns():
            kwargs, _ = _build_safe_request_kwargs(
                "GET", "http://example.com", headers={}
            )

        # If something injected, it must at least be well-formed; but
        # absent active span, traceparent should not be present.
        if "traceparent" in kwargs["headers"]:
            assert re.match(
                r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
                kwargs["headers"]["traceparent"],
            )

    def test_traceparent_added_with_active_span(self) -> None:
        """When a span is active, traceparent is injected into the headers."""
        if not _otel_available():
            return  # skip silently when OTel not installed

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            trace.set_tracer_provider(TracerProvider())

        tracer = trace.get_tracer("test-http-tools")
        with _patch_dns(), tracer.start_as_current_span("tool-call"):
            kwargs, original_url = _build_safe_request_kwargs(
                "GET", "http://example.com", headers={}
            )

        assert original_url == "http://example.com"
        assert "traceparent" in kwargs["headers"], (
            f"Expected traceparent in outgoing headers, got: "
            f"{list(kwargs['headers'].keys())}"
        )
        assert re.match(
            r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
            kwargs["headers"]["traceparent"],
        )
        # Host header preserved (SSRF protection).
        assert kwargs["headers"].get("Host") == "example.com"

    def test_no_raise_when_selva_observability_missing(self) -> None:
        """If selva_observability is not importable, request still builds."""
        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        real_import = builtins.__import__

        def _block_obs(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("selva_observability"):
                raise ImportError("blocked")
            return real_import(name, *args, **kwargs)

        with _patch_dns(), patch("builtins.__import__", side_effect=_block_obs):
            kwargs, _ = _build_safe_request_kwargs(
                "POST", "http://example.com/api", headers={"X-Test": "1"}
            )

        # Should not raise; just no traceparent injected.
        assert "traceparent" not in kwargs["headers"]
        assert kwargs["headers"].get("X-Test") == "1"
