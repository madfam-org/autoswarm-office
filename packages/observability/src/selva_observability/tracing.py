"""OpenTelemetry tracing initialization.

No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is not set.  Follows the same
env-gated pattern as ``init_sentry()``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_tracing(service_name: str) -> None:
    """Initialize OpenTelemetry tracing if OTEL_EXPORTER_OTLP_ENDPOINT is set.

    This is intentionally a no-op when the env var is absent, allowing
    the same code to run in dev (no tracing) and production (with tracing).
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("OTEL_EXPORTER_OTLP_ENDPOINT not set -- tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "opentelemetry packages not installed -- tracing disabled. "
            "Install with: pip install selva-observability[tracing]"
        )
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=not endpoint.startswith("https"),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry tracing initialized for %s -> %s",
        service_name,
        endpoint,
    )
