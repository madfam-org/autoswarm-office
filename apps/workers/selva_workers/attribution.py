"""Worker-side attribution emitter for the T3.2 funnel.

The worker is the first hop after the nexus-api webhook handler that can
actually observe whether the user-facing action (email send, SMS, etc.)
succeeded. This module emits `playbook.sent` to PostHog when a send
succeeds, preserving the anonymous `lead_id` as the distinct_id.

Keeps the same contract as `nexus_api.attribution.emit_playbook_sent`
but lives in the worker package so we don't cross the import boundary
(workers must not depend on `nexus_api`).

Falls back to structured logging when PostHog is not configured.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Event names — mirror nexus_api.attribution so the contract stays single-sourced.
EVENT_LEAD_QUALIFIED = "lead.qualified"
EVENT_PLAYBOOK_SENT = "playbook.sent"

_client: Any = None
_init_attempted = False


def _lazy_init() -> None:
    global _client, _init_attempted  # noqa: PLW0603
    if _init_attempted:
        return
    _init_attempted = True

    api_key = os.environ.get("POSTHOG_API_KEY") or os.environ.get("POSTHOG_PROJECT_API_KEY")
    if not api_key:
        logger.debug("Attribution: POSTHOG_API_KEY not set, events will be logged only")
        return
    try:
        import posthog

        posthog.api_key = api_key
        posthog.host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
        _client = posthog
    except ImportError:
        logger.debug("posthog package not installed in worker; emitting log-only events")


def _track(distinct_id: str, event: str, properties: dict[str, Any]) -> None:
    """Emit to PostHog if configured, otherwise log structured JSON."""
    _lazy_init()
    if _client is None:
        logger.info(
            "[attribution] distinct_id=%s event=%s props=%s",
            distinct_id,
            event,
            properties,
        )
        return
    try:
        _client.capture(distinct_id, event, properties=properties)
    except Exception:
        logger.warning("PostHog capture failed for event=%s", event, exc_info=True)


def emit_playbook_sent(
    lead_id: str,
    *,
    playbook_name: str,
    task_id: str,
    channel: str,
    recipient_domain: str | None = None,
    utm_campaign: str = "hot_lead_auto",
    extra: dict[str, Any] | None = None,
) -> None:
    """Worker-side twin of `nexus_api.attribution.emit_playbook_sent`."""
    if not lead_id:
        logger.debug("emit_playbook_sent: empty lead_id, skipping")
        return
    properties: dict[str, Any] = {
        "lead_id": lead_id,
        "playbook": playbook_name,
        "task_id": task_id,
        "channel": channel,
        "utm_campaign": utm_campaign,
    }
    if recipient_domain:
        properties["recipient_domain"] = recipient_domain
    if extra:
        properties.update(extra)
    _track(lead_id, EVENT_PLAYBOOK_SENT, properties)


def domain_of(email: str) -> str | None:
    if not isinstance(email, str) or "@" not in email:
        return None
    _, _, domain = email.partition("@")
    return domain.lower().strip() or None
