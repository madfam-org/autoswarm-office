"""Server-side W3C Trace Context extraction middleware.

When an inbound request carries a ``traceparent`` header (and optionally
``tracestate``) this middleware extracts the parent context and attaches
it for the duration of the request. Any spans created inside the request
handler — by the OpenTelemetry SDK directly, by an instrumented library,
or by any code path that calls ``trace.get_current_span()`` — will then
be children of the upstream span, giving us correlated traces across the
caller (worker, office-ui, Janua, …) and the nexus-api request handler.

Behaviour when OpenTelemetry is NOT installed:
  - ``selva_observability.extract_trace_context`` returns ``None``,
  - ``opentelemetry.context.attach`` import fails,
  - we silently skip both and just call the next ASGI handler.

Behaviour when OpenTelemetry IS installed but no provider has been
initialised (no ``OTEL_EXPORTER_OTLP_ENDPOINT`` set):
  - ``extract`` returns a context that points at the upstream span_id
    even though we don't have a SDK to do anything with it. Spans
    created with that context are valid but never exported. This is
    intentional — it means propagation works the moment an exporter
    is wired without any code change.

Mounted in ``main.py`` BEFORE ``RequestIdMiddleware`` so that the
request-id middleware (which formats outgoing ``traceparent`` from the
*current* span context) sees the propagated parent.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from selva_observability import extract_trace_context

logger = logging.getLogger(__name__)


class TraceContextMiddleware(BaseHTTPMiddleware):
    """Extract W3C ``traceparent`` from incoming headers and attach it.

    No-op when no parent context is present or when OpenTelemetry is
    not installed.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Cheap path: if there's no traceparent header at all, skip the
        # opentelemetry import dance entirely.
        if "traceparent" not in {k.lower() for k in request.headers}:
            return await call_next(request)

        parent_ctx = extract_trace_context(request.headers)
        if parent_ctx is None:
            return await call_next(request)

        try:
            from opentelemetry import context as otel_context
        except ImportError:
            # Should not happen — extract_trace_context succeeded — but be
            # defensive.
            return await call_next(request)

        token = otel_context.attach(parent_ctx)
        try:
            return await call_next(request)
        finally:
            try:
                otel_context.detach(token)
            except Exception as exc:  # pragma: no cover -- defensive
                logger.debug("otel context detach failed: %s", exc)
