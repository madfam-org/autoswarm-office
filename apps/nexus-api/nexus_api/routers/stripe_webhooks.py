"""Stripe webhook handler -- signature verification + per-event dispatch.

Phase 2.7 -- per-event handlers wired up. The endpoint verifies the
Stripe signature (fail-closed on missing secret / bad signature /
replay) and routes to a handler keyed on ``event["type"]``. Handlers
that match an unhandled event type fall through to ``_handle_unknown``
which logs at INFO and 200s (Stripe retries non-2xx aggressively, so
silent acknowledgement is the documented best practice for events the
endpoint does not yet act on).

Currently handled events:

- ``customer.subscription.created`` -- new tenant subscription; mirror
  status + tier into ``tenant_configs``.
- ``customer.subscription.updated`` -- tier change, renewal, or status
  change; refresh the same columns + the cached daily-task limit so
  budget enforcement reflects the new tier on the next dispatch.
- ``customer.subscription.deleted`` -- cancellation; mark the row as
  ``cancelled`` and let the existing dunning logic schedule the
  grace-period downgrade. We do NOT immediately wipe the tier so the
  tenant can keep dispatching until ``current_period_end``.
- ``invoice.paid`` -- successful payment. Clears the ``tier_overage``
  Redis cache key so usage caps reset for the new period and emits a
  ``billing.invoice_paid`` task event so the UI surfaces the receipt.
- ``invoice.payment_failed`` -- failed charge. Marks the subscription
  as ``past_due`` and emits ``billing.payment_failed`` so the office UI
  can surface a banner. We do NOT immediately downgrade -- Stripe
  retries on its own dunning schedule.

The fail-closed pattern matches the v2.2.x webhook hardening:

- Missing webhook secret → 503 (endpoint not configured)
- Invalid signature → 401
- Unknown event type → 200 + log (Stripe retries on non-2xx)
- Tenant not found for a known event → 200 + log (test events,
  pre-backfill events, manual Stripe Dashboard tests). We do not 500
  here; that would put the endpoint into a Stripe retry loop on every
  event from a tenant we have not yet provisioned in the DB.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..billing_tiers import DEFAULT_TIER
from ..config import get_settings
from ..database import tenant_session
from ..models import TenantConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stripe", tags=["webhooks"])

# Stripe replay-attack tolerance: reject events whose signed timestamp is
# older than this. Stripe's default in their library is 300s (5 minutes),
# matching our other webhook handlers. Don't widen without ops review.
_SIGNATURE_TOLERANCE_SECONDS = 300


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, str]:
    """Verify Stripe signature; dispatch event to per-type handlers."""
    settings = get_settings()

    if settings.billing_via_dhanam:
        logger.warning(
            "Direct Stripe webhook rejected — billing routes through Dhanam. "
            "Configure Stripe webhooks on Dhanam and point Selva at "
            "/api/v1/billing/webhooks/dhanam."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "billing routes through Dhanam; direct Stripe webhook is break-glass only "
                "(set BILLING_VIA_DHANAM=false to enable legacy path)"
            ),
        )

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


# ---------------------------------------------------------------------------
# Tenant resolution helper
# ---------------------------------------------------------------------------


async def _resolve_tenant_by_stripe_customer(
    db: AsyncSession, customer_id: str
) -> TenantConfig | None:
    """Find the ``tenant_configs`` row whose ``stripe_customer_id`` matches.

    Returns ``None`` if no tenant is registered against this customer ID
    (could happen for events fired before backfill, for manual Stripe
    Dashboard test events, or for events fired against a customer who has
    been removed from the DB). Callers MUST treat ``None`` as "log + 200"
    rather than 5xx -- a non-2xx response here would put us in a Stripe
    retry loop on every test event the operator fires.
    """
    if not customer_id:
        return None
    result = await db.execute(
        select(TenantConfig).where(TenantConfig.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Event-payload extraction helpers
# ---------------------------------------------------------------------------


def _extract_customer_id(event: Any) -> str:
    """Pull the Stripe customer ID off any subscription / invoice event."""
    obj = event["data"]["object"]
    customer = obj.get("customer", "")
    # Stripe expands `customer` to the full Customer object when the event
    # was created with expand. Handle both the bare-string and dict cases.
    if isinstance(customer, dict):
        customer = customer.get("id", "")
    return str(customer or "")


def _extract_subscription_tier(subscription_obj: dict[str, Any]) -> str:
    """Resolve the Selva tier slug from a Stripe subscription's price ID.

    Looks up the price ID against ``Settings.stripe_price_to_tier_map``.
    Falls back to ``DEFAULT_TIER`` (matching ``billing.py`` /
    ``billing_internal.py``) when the price ID is missing from the map --
    this protects against the operator forgetting to wire a new price ID
    after launch, but logs a warning so the gap is visible in ops.
    """
    settings = get_settings()
    items = subscription_obj.get("items", {}).get("data", [])
    if not items:
        logger.warning(
            "Stripe subscription has no items; defaulting to %s tier", DEFAULT_TIER
        )
        return DEFAULT_TIER
    price_id = items[0].get("price", {}).get("id", "")
    tier = settings.stripe_price_to_tier_map.get(price_id)
    if not tier:
        logger.warning(
            "Stripe price_id=%s missing from STRIPE_PRICE_TO_TIER_MAP; "
            "defaulting to %s tier. Add the mapping to Settings.",
            price_id,
            DEFAULT_TIER,
        )
        return DEFAULT_TIER
    return tier


def _coerce_period_end(subscription_obj: dict[str, Any]) -> datetime | None:
    """Convert Stripe's epoch ``current_period_end`` into a UTC datetime."""
    raw = subscription_obj.get("current_period_end")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OSError):
        logger.warning("Could not coerce current_period_end=%r to datetime", raw)
        return None


async def _cache_tier_limit(org_id: str, tier: str) -> None:
    from ..services.billing_sync import cache_tier_limit

    await cache_tier_limit(org_id, tier)


async def _clear_overage_counter(org_id: str) -> None:
    from ..services.billing_sync import clear_overage_counter

    await clear_overage_counter(org_id)


# ---------------------------------------------------------------------------
# Per-event handlers
# ---------------------------------------------------------------------------


async def _handle_unknown(event: Any) -> None:
    """Default handler -- log unknown events but 200 so Stripe doesn't retry."""
    logger.info(
        "Stripe event received with no specific handler: type=%s id=%s",
        event["type"],
        event["id"],
    )


async def _handle_subscription_created(event: Any) -> None:
    """customer.subscription.created -- new tenant subscription.

    Looks up the tenant by ``stripe_customer_id``, mirrors
    ``subscription_status`` + ``subscription_tier`` + the period end, and
    refreshes the cached tier limit so the next dispatch sees the new
    quota.
    """
    sub_obj = event["data"]["object"]
    customer_id = _extract_customer_id(event)
    sub_id = str(sub_obj.get("id", ""))

    async with tenant_session("platform") as db:
        tenant = await _resolve_tenant_by_stripe_customer(db, customer_id)
        if tenant is None:
            logger.info(
                "subscription.created for unknown customer=%s (sub=%s); "
                "skipping (likely test event or pre-backfill)",
                customer_id,
                sub_id,
            )
            return

        tier = _extract_subscription_tier(sub_obj)
        tenant.stripe_subscription_id = sub_id
        tenant.subscription_status = str(sub_obj.get("status", "active"))
        tenant.subscription_tier = tier
        tenant.subscription_current_period_end = _coerce_period_end(sub_obj)
        await db.commit()

        await _cache_tier_limit(tenant.org_id, tier)

    logger.info(
        "subscription.created processed: org=%s sub=%s tier=%s",
        tenant.org_id,
        sub_id,
        tier,
    )


async def _handle_subscription_updated(event: Any) -> None:
    """customer.subscription.updated -- tier change, renewal, status change."""
    sub_obj = event["data"]["object"]
    customer_id = _extract_customer_id(event)
    sub_id = str(sub_obj.get("id", ""))

    async with tenant_session("platform") as db:
        tenant = await _resolve_tenant_by_stripe_customer(db, customer_id)
        if tenant is None:
            logger.info(
                "subscription.updated for unknown customer=%s (sub=%s); skipping",
                customer_id,
                sub_id,
            )
            return

        tier = _extract_subscription_tier(sub_obj)
        new_status = str(sub_obj.get("status", tenant.subscription_status or "active"))
        previous_tier = tenant.subscription_tier
        tenant.stripe_subscription_id = sub_id
        tenant.subscription_status = new_status
        tenant.subscription_tier = tier
        tenant.subscription_current_period_end = _coerce_period_end(sub_obj)
        await db.commit()

        # Always refresh the cached tier limit; even if the tier itself
        # didn't change, the period boundary may have rolled.
        await _cache_tier_limit(tenant.org_id, tier)

    logger.info(
        "subscription.updated processed: org=%s sub=%s tier=%s→%s status=%s",
        tenant.org_id,
        sub_id,
        previous_tier,
        tier,
        new_status,
    )


async def _handle_subscription_deleted(event: Any) -> None:
    """customer.subscription.deleted -- cancellation.

    Marks status as ``cancelled`` but DOES NOT immediately wipe the tier --
    the tenant retains access until ``current_period_end`` per the
    standard SaaS grace-period model. Downstream dunning / downgrade logic
    can read the ``cancelled`` status + period end to schedule the
    transition to the free tier.
    """
    sub_obj = event["data"]["object"]
    customer_id = _extract_customer_id(event)
    sub_id = str(sub_obj.get("id", ""))

    async with tenant_session("platform") as db:
        tenant = await _resolve_tenant_by_stripe_customer(db, customer_id)
        if tenant is None:
            logger.info(
                "subscription.deleted for unknown customer=%s (sub=%s); skipping",
                customer_id,
                sub_id,
            )
            return

        tenant.subscription_status = "cancelled"
        # Preserve subscription_tier + period end so the grace-period
        # downgrade scheduler has the context it needs.
        tenant.subscription_current_period_end = _coerce_period_end(sub_obj)
        await db.commit()

    logger.info(
        "subscription.deleted processed: org=%s sub=%s "
        "(grace until current_period_end)",
        tenant.org_id,
        sub_id,
    )


async def _handle_invoice_paid(event: Any) -> None:
    """invoice.paid -- successful payment.

    Clears the daily overage counter (if any) so usage caps reset for the
    new billing period, and emits a ``billing.invoice_paid`` task event so
    the office UI can surface the receipt.
    """
    inv_obj = event["data"]["object"]
    customer_id = _extract_customer_id(event)
    invoice_id = str(inv_obj.get("id", ""))
    amount_paid = int(inv_obj.get("amount_paid", 0))
    currency = str(inv_obj.get("currency", "")).upper()

    async with tenant_session("platform") as db:
        tenant = await _resolve_tenant_by_stripe_customer(db, customer_id)
        if tenant is None:
            logger.info(
                "invoice.paid for unknown customer=%s (invoice=%s); skipping",
                customer_id,
                invoice_id,
            )
            return

        # If the previous status was ``past_due`` and the dunning attempt
        # cleared, restore ``active``. Stripe typically also fires a
        # subscription.updated, but order is not guaranteed -- be tolerant.
        if tenant.subscription_status == "past_due":
            tenant.subscription_status = "active"
            await db.commit()

        # Late import to avoid the events router → stripe_webhooks circular
        # risk (events imports nothing from us, but mirrors the pattern in
        # approvals.py / swarms.py / onboarding.py).
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="billing.invoice_paid",
            event_category="billing",
            org_id=tenant.org_id,
            payload={
                "stripe_invoice_id": invoice_id,
                "amount_paid": amount_paid,
                "currency": currency,
                "stripe_customer_id": customer_id,
            },
        )
        await db.commit()

        await _clear_overage_counter(tenant.org_id)

    logger.info(
        "invoice.paid processed: org=%s invoice=%s amount=%s %s",
        tenant.org_id,
        invoice_id,
        amount_paid,
        currency,
    )


async def _handle_invoice_payment_failed(event: Any) -> None:
    """invoice.payment_failed -- failed charge.

    Marks the subscription as ``past_due`` and emits a task event so the
    office UI can surface a "payment failed" banner. We DO NOT downgrade
    the tier here -- Stripe handles dunning on its own retry schedule and
    will fire ``customer.subscription.deleted`` if it gives up.
    """
    inv_obj = event["data"]["object"]
    customer_id = _extract_customer_id(event)
    invoice_id = str(inv_obj.get("id", ""))
    amount_due = int(inv_obj.get("amount_due", 0))
    currency = str(inv_obj.get("currency", "")).upper()
    next_attempt = inv_obj.get("next_payment_attempt")

    async with tenant_session("platform") as db:
        tenant = await _resolve_tenant_by_stripe_customer(db, customer_id)
        if tenant is None:
            logger.info(
                "invoice.payment_failed for unknown customer=%s (invoice=%s); skipping",
                customer_id,
                invoice_id,
            )
            return

        tenant.subscription_status = "past_due"
        await db.commit()

        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="billing.payment_failed",
            event_category="billing",
            org_id=tenant.org_id,
            payload={
                "stripe_invoice_id": invoice_id,
                "amount_due": amount_due,
                "currency": currency,
                "stripe_customer_id": customer_id,
                "next_payment_attempt": next_attempt,
            },
        )
        await db.commit()

    logger.warning(
        "invoice.payment_failed processed: org=%s invoice=%s amount=%s %s "
        "next_attempt=%s",
        tenant.org_id,
        invoice_id,
        amount_due,
        currency,
        next_attempt,
    )


# Map of stripe event type → handler. New entries follow the same pattern:
# late-import any router-level dependency to avoid circular imports, run all
# DB writes inside a single tenant_session("platform") block, never raise out
# (Stripe retries on non-2xx).
_EVENT_HANDLERS: dict[str, Callable[[Any], Awaitable[None]]] = {
    "customer.subscription.created": _handle_subscription_created,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}
