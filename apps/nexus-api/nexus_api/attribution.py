"""Attribution glue — preserves `lead_id` across the conversion funnel.

T3.2 contract (see /internal-devops/docs/attribution-contract.md):

    lead.captured (phynd-crm)
        -> lead.qualified (selva-office, this module)
            -> playbook.sent (selva-office, this module)
                -> checkout.completed (dhanam)
                    -> subscription.created (dhanam)

The `lead_id` is an opaque string — typically a UUID4 minted by PhyndCRM
when a lead is first captured. This module:

1. Extracts a stable `lead_id` from inbound CRM events. When PhyndCRM
   does not provide one, a deterministic fallback is derived from
   (contact_email, activity_id) so retries collapse to the same id.
2. Emits PostHog events with `distinct_id = lead_id` so the funnel is
   anonymous up to conversion. Dhanam will call `posthog.alias()`
   when the lead converts to link the anonymous `lead_id` to the
   authenticated `user_sub`.

The `lead_id` MUST be threaded through every hop:
- CRM webhook -> SwarmTask.payload["lead_id"]
- SwarmTask.payload -> CRM graph state["lead_id"]
- graph state -> email tool metadata (utm_campaign + reply-to chain)
- email send -> PostHog `playbook.sent` event

Keep this module dependency-light: it is imported from webhook handlers
that must not pull heavy graph / worker code.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from .analytics import track

logger = logging.getLogger(__name__)

# Event names for the attribution funnel. Centralised here so downstream
# repos (phynd-crm, dhanam) can import the same constants once this
# module is re-exported via a shared package.
EVENT_LEAD_CAPTURED = "lead.captured"  # emitted by phynd-crm
EVENT_LEAD_QUALIFIED = "lead.qualified"  # emitted here
EVENT_PLAYBOOK_SENT = "playbook.sent"  # emitted here
EVENT_CHECKOUT_COMPLETED = "checkout.completed"  # emitted by dhanam
EVENT_SUBSCRIPTION_CREATED = "subscription.created"  # emitted by dhanam
# Public-social outbound (Reddit MVP, X/LinkedIn later). The funnel hop
# is post → engagement → (optional) lead.captured if the click lands on
# a tracked CTA. We deliberately use ``post_id`` (not ``lead_id``) as
# distinct_id at the source-of-truth event because no lead exists yet —
# Dhanam will alias() once a click converts.
EVENT_OUTBOUND_POST_CREATED = "outbound_post.created"  # emitted by reddit_tools
EVENT_OUTBOUND_POST_ENGAGED = "outbound_post.engaged"  # emitted by engagement webhook


def extract_lead_id(crm_event_data: dict[str, Any]) -> str:
    """Return a stable `lead_id` for a CRM event.

    Preference order:
        1. `crm_event_data["lead_id"]` (preferred, PhyndCRM-minted UUID)
        2. `crm_event_data["id"]` (PhyndCRM contact id)
        3. Deterministic SHA-256 fallback over contact_email + activity_id
        4. Freshly minted UUID4 (last resort — breaks dedup guarantees)

    The returned id is always a non-empty string, URL-safe.
    """
    explicit = crm_event_data.get("lead_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    contact_id = crm_event_data.get("id") or crm_event_data.get("contact_id")
    if isinstance(contact_id, str) and contact_id.strip():
        return contact_id.strip()

    # Deterministic fallback: derive a stable id from contact identifiers
    # so webhook retries do not mint new lead ids.
    contact_email = str(crm_event_data.get("contact_email") or crm_event_data.get("email") or "")
    activity_id = str(crm_event_data.get("activity_id") or "")
    if contact_email or activity_id:
        seed = f"{contact_email}|{activity_id}".encode()
        digest = hashlib.sha256(seed).hexdigest()[:32]
        return f"lead_{digest}"

    # Last resort — non-deterministic. Log so we notice in staging.
    fallback = str(uuid.uuid4())
    logger.warning(
        "extract_lead_id: no stable identifiers in CRM event, minted fresh uuid=%s",
        fallback,
    )
    return fallback


def emit_lead_qualified(
    lead_id: str,
    *,
    trigger_event: str,
    playbook_name: str,
    task_id: str,
    utm_source: str = "selva",
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit `lead.qualified` when a CRM event matches a playbook.

    `distinct_id` is the anonymous `lead_id` — never the contact email
    (using the email would fork the funnel into a second distinct_id
    once the user authenticates with Janua / Dhanam).
    """
    if not lead_id:
        logger.debug("emit_lead_qualified: empty lead_id, skipping")
        return
    properties: dict[str, Any] = {
        "lead_id": lead_id,
        "trigger_event": trigger_event,
        "playbook": playbook_name,
        "task_id": task_id,
        "utm_source": utm_source,
    }
    if extra:
        properties.update(extra)
    track(lead_id, EVENT_LEAD_QUALIFIED, properties)


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
    """Emit `playbook.sent` after a playbook successfully dispatches a
    user-facing action (email, SMS, etc.).

    `recipient_domain` intentionally excludes the local-part of the
    email to keep the event PII-safe while still enabling domain-level
    funnel segmentation.
    """
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
    track(lead_id, EVENT_PLAYBOOK_SENT, properties)


def domain_of(email: str) -> str | None:
    """Return the domain part of an email address, or None."""
    if not isinstance(email, str) or "@" not in email:
        return None
    _, _, domain = email.partition("@")
    return domain.lower().strip() or None


def emit_outbound_post_created(
    post_id: str,
    *,
    subreddit: str,
    persona_id: str,
    disclosure_applied: bool,
    platform: str = "reddit",
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit ``outbound_post.created`` after a successful public-social post.

    ``distinct_id`` is the platform-issued ``post_id`` — it's the only
    immutable identifier we have at this stage (no lead exists yet). When
    a click on the post converts later, Dhanam's ``checkout.completed``
    handler aliases the engagement chain to the authenticated user_sub.

    The ``disclosure_applied`` flag flows through to dashboards so we
    can answer "did every post we made carry the AI-disclosure footer?"
    in a single PostHog query.
    """
    if not post_id:
        logger.debug("emit_outbound_post_created: empty post_id, skipping")
        return
    properties: dict[str, Any] = {
        "post_id": post_id,
        "subreddit": subreddit,
        "persona_id": persona_id,
        "platform": platform,
        "disclosure_applied": disclosure_applied,
    }
    if extra:
        properties.update(extra)
    track(post_id, EVENT_OUTBOUND_POST_CREATED, properties)


def emit_outbound_post_engaged(
    post_id: str,
    *,
    click_count: int,
    subscription_id_if_converted: str | None = None,
    platform: str = "reddit",
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit ``outbound_post.engaged`` when our tracking webhook records
    user interaction on a previously-emitted ``outbound_post.created``.

    ``subscription_id_if_converted`` is None for the click-only case;
    populated when the click chain led to a Stripe subscription so the
    funnel can compute attribution lift per subreddit.
    """
    if not post_id:
        logger.debug("emit_outbound_post_engaged: empty post_id, skipping")
        return
    properties: dict[str, Any] = {
        "post_id": post_id,
        "click_count": click_count,
        "platform": platform,
    }
    if subscription_id_if_converted:
        properties["subscription_id"] = subscription_id_if_converted
        properties["converted"] = True
    else:
        properties["converted"] = False
    if extra:
        properties.update(extra)
    track(post_id, EVENT_OUTBOUND_POST_ENGAGED, properties)
