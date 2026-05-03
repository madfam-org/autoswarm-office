"""Request ID propagation middleware with structlog context binding."""

from __future__ import annotations

import logging
import uuid

import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def _get_current_span_context() -> str | None:
    """Extract W3C traceparent from current OTel span, if available."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace import format_span_id, format_trace_id

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return (
                f"00-{format_trace_id(ctx.trace_id)}"
                f"-{format_span_id(ctx.span_id)}"
                f"-{ctx.trace_flags:02x}"
            )
    except ImportError:
        logger.debug("OpenTelemetry not installed; skipping traceparent propagation")
    return None


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generates a unique X-Request-ID for each request.

    If the incoming request already carries an ``X-Request-ID`` header the
    existing value is preserved.  The ID is stored on ``request.state``,
    echoed in the response headers, and bound to structlog contextvars
    for automatic inclusion in all log events during the request.

    When OpenTelemetry is active, the W3C ``traceparent`` header is also
    set on the response for distributed trace correlation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Bind to structlog contextvars so all logs in this request include request_id.
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # Propagate W3C traceparent if OpenTelemetry is active.
        traceparent = _get_current_span_context()
        if traceparent:
            response.headers["traceparent"] = traceparent

        # Clear contextvars after response to prevent leaking between requests.
        structlog.contextvars.clear_contextvars()

        return response
