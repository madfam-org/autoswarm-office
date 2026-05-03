"""Stripe webhook handler — signature verification + per-event dispatch.

Phase 1 scaffold. Today this verifies signatures and 200s on every event;
real per-event handlers (subscription.created, invoice.paid, etc.) land in
follow-up PRs as each event becomes operationally relevant.

The fail-closed pattern matches the v2.2.x webhook hardening:
- Missing webhook secret → 503 (endpoint not configured)
- Invalid signature → 401
- Unknown event type → 200 + log (Stripe retries on non-2xx)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request, status

from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stripe", tags=["webhooks"])

# Stripe replay-attack tolerance: reject events whose signed timestamp is
# older than this. Stripe's default in their library is 300s (5 minutes),
# matching our other webhook handlers. Don't widen without ops review.
_SIGNATURE_TOLERANCE_SECONDS = 300


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, str]:
    """Verify Stripe signature; dispatch event to per-type handlers.

    Stub event handlers log + 200 today. Real implementations land in
    follow-up PRs as each event type is needed (subscription.created,
    invoice.paid, payment_intent.succeeded, etc.).
    """
    settings = get_settings()

    if not settings.stripe_webhook_secret:
        logger.error(
            "Stripe webhook received but STRIPE_WEBHOOK_SECRET is unset; "
            "endpoint not configured. Set the secret from Stripe Dashboard → "
            "Developers → Webhooks → reveal signing secret."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stripe webhook endpoint not configured",
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
            tolerance=_SIGNATURE_TOLERANCE_SECONDS,
        )
    except ValueError as exc:
        # Malformed JSON — Stripe should never send this, but harden anyway.
        logger.warning("Stripe webhook payload parse failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid payload",
        ) from exc
    except stripe.SignatureVerificationError as exc:
        # Wrong signing secret OR replay outside tolerance OR forged.
        # Log only the prefix of the sig header to avoid log spam from
        # randomly-formatted attacker payloads.
        logger.warning(
            "Stripe webhook signature verification failed (sig_header_prefix=%s)",
            sig_header[:32],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        ) from exc

    handler = _EVENT_HANDLERS.get(event["type"], _handle_unknown)
    await handler(event)

    return {"status": "received", "event_id": event["id"]}


async def _handle_unknown(event: Any) -> None:
    """Default handler — log unknown events but 200 so Stripe doesn't retry.

    Stripe retries failed webhooks aggressively (up to 3 days). Returning
    200 on unknown events is the documented best practice for endpoints
    that are still scaffolding.
    """
    logger.info(
        "Stripe event received with no specific handler: type=%s id=%s",
        event["type"],
        event["id"],
    )


# Map of stripe event type → handler. Add entries as event types become
# operationally relevant per ROADMAP.md Phase 2 (tier upgrades, dunning,
# refunds, etc.).
_EVENT_HANDLERS: dict[str, Callable[[Any], Awaitable[None]]] = {
    # "customer.subscription.created": _handle_subscription_created,
    # "customer.subscription.updated": _handle_subscription_updated,
    # "customer.subscription.deleted": _handle_subscription_deleted,
    # "invoice.paid": _handle_invoice_paid,
    # "invoice.payment_failed": _handle_invoice_payment_failed,
    # "payment_intent.succeeded": _handle_payment_intent_succeeded,
}
