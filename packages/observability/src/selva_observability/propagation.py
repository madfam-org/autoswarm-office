"""W3C Trace Context propagation helpers.

These helpers wrap ``opentelemetry.propagate.inject`` and
``opentelemetry.propagate.extract`` so callers don't need to import
opentelemetry directly. They are no-ops (or context-preserving fallbacks)
when the OpenTelemetry SDK is not installed or no provider has been
initialised, matching the same env-gated pattern as ``init_tracing``.

Two consumer-facing call sites in Selva use this:

1. ``apps/workers/selva_workers/auth.py:get_worker_auth_headers`` —
   injects ``traceparent`` (and ``tracestate`` if present) on every
   worker → nexus-api request so the API-side span becomes a child of
   the worker-side span.
2. ``packages/tools/src/selva_tools/builtins/http_tools.py:_build_safe_request_kwargs`` —
   same injection on every tool-originated outbound HTTP call.

The corresponding extraction happens server-side in
``apps/nexus-api/nexus_api/middleware/tracing.py:TraceContextMiddleware``,
which extracts the parent context off the incoming request and attaches
it so any spans created by the request handler become children of the
caller's span.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Inject W3C ``traceparent`` (and ``tracestate``) into a headers dict.

    Mutates ``headers`` in place AND returns it for caller convenience.

    No-op if:
      - ``opentelemetry`` is not installed,
      - no tracer provider has been initialised, or
      - there is no active span (the propagator simply writes nothing).

    Returns the same dict instance that was passed in.
    """
    try:
        from opentelemetry.propagate import inject
    except ImportError:
        # OTel not installed (dev environment without tracing extras)
        logger.debug("opentelemetry.propagate not available; skipping trace inject")
        return headers
    except Exception as exc:  # pragma: no cover -- defensive
        logger.debug("trace inject failed: %s", exc)
        return headers

    try:
        inject(headers)
    except Exception as exc:  # pragma: no cover -- defensive
        # Never let a tracing failure break the actual request.
        logger.debug("inject() raised; continuing without trace headers: %s", exc)
    return headers


def extract_trace_context(headers: dict[str, str] | Any) -> Any:
    """Extract a parent ``Context`` from incoming request headers.

    Returns an opaque ``opentelemetry.context.Context`` object that
    should be passed to ``opentelemetry.context.attach()`` (or used as
    the ``context=`` argument to ``tracer.start_as_current_span``) so
    that spans created in the request handler inherit the caller's
    trace_id and become children of the caller's span.

    Returns ``None`` when:
      - opentelemetry is not installed,
      - no ``traceparent`` header is present, or
      - the header is malformed and the propagator returns the empty
        context (we treat that as "no parent" for caller convenience).

    The returned object is intentionally typed ``Any`` so callers don't
    need to depend on opentelemetry types in their public API.
    """
    try:
        from opentelemetry.propagate import extract
    except ImportError:
        return None
    except Exception as exc:  # pragma: no cover -- defensive
        logger.debug("trace extract import failed: %s", exc)
        return None

    try:
        # propagate.extract accepts a Mapping[str, str]; FastAPI Headers
        # is mapping-compatible. We coerce to dict to be defensive about
        # case-insensitive access (W3C requires lowercase header names).
        if hasattr(headers, "items"):
            normalised = {k.lower(): v for k, v in headers.items()}
        else:
            normalised = dict(headers)
        ctx = extract(normalised)
        return ctx if ctx else None
    except Exception as exc:  # pragma: no cover -- defensive
        logger.debug("extract() raised; treating as no parent context: %s", exc)
        return None


__all__ = ["extract_trace_context", "inject_trace_context"]
