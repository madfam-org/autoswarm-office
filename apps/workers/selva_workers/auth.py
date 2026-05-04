"""Worker-to-API authentication helpers."""

from __future__ import annotations


def get_worker_auth_headers(org_id: str | None = None) -> dict[str, str]:
    """Return Authorization headers for worker-to-API calls.

    Reads the token from ``WORKER_API_TOKEN`` env var (via settings).

    The returned dict is also seeded with W3C ``traceparent`` (and
    ``tracestate`` when present) when an OpenTelemetry span is active,
    so that the receiving nexus-api ``TraceContextMiddleware`` can
    attach the parent context and emit child spans correlated with the
    worker-side trace. When OTel is not installed or no span is active
    the injection is a silent no-op — this stays compatible with dev
    environments that don't have the tracing extras installed.

    Args:
        org_id: Target tenant org_id. Required for tenant-scoped operations
            (task events, voice-mode lookup, billing, agent stats, etc.).
            Sent as the ``X-Selva-Tenant-Org`` header so nexus-api ``auth.py``
            can populate ``user["org_id"]`` correctly for the worker token
            path. Omit only for genuinely platform-scoped service calls
            (audit writes, queue stats) where the receiving endpoint
            verifies the ``service`` role.
    """
    from .config import get_settings

    headers = {"Authorization": f"Bearer {get_settings().worker_api_token}"}
    if org_id:
        headers["X-Selva-Tenant-Org"] = org_id

    # Inject W3C trace context AFTER all other headers are set so the
    # propagator overwrites any stale traceparent that may have been
    # passed in. No-op when OTel is not installed / no active span.
    try:
        from selva_observability import inject_trace_context

        inject_trace_context(headers)
    except ImportError:
        # selva_observability is a hard dep but stay defensive in case
        # the worker is run with a stripped-down install.
        pass

    return headers
