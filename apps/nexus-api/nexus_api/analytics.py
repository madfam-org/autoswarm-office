"""PostHog analytics integration for Selva Nexus API."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# `_client` is the optional `posthog` module after init.  It is typed as
# `Any` because the `posthog` package ships no type stubs; using a tighter
# type would force every call site to carry a `# type: ignore[union-attr]`.
_client: Any | None = None


def init_posthog() -> None:
    """Initialize PostHog client from centralized Settings."""
    global _client  # noqa: PLW0603
    from .config import get_settings

    settings = get_settings()
    if not settings.posthog_api_key:
        return
    try:
        import posthog

        posthog.api_key = settings.posthog_api_key
        posthog.host = settings.posthog_host
        _client = posthog
    except ImportError:
        pass


def track(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Capture a PostHog event."""
    if _client is None:
        return
    with contextlib.suppress(Exception):
        _client.capture(distinct_id, event, properties=properties or {})


def identify(distinct_id: str, properties: dict[str, Any] | None = None) -> None:
    """Set person properties on a PostHog user."""
    if not _client:
        return
    try:
        _client.identify(distinct_id, properties or {})
    except Exception:
        logger.debug("PostHog identify failed for %s", distinct_id, exc_info=True)


def shutdown() -> None:
    """Flush and shut down the PostHog client."""
    if _client is None:
        return
    with contextlib.suppress(Exception):
        _client.shutdown()
