"""Canonical subscription sync for Selva tenants (Dhanam-first billing router).

Envelope contract (pinned against Dhanam's source, verified 2026-07-28):

Subscription events are built by Dhanam's ``notifyProductWebhooks``
(``apps/api/src/modules/billing/services/subscription-janua-notifier.service.ts:137-148``)
and delivered per-product (the dispatcher routes on the ``{product}_`` prefix
of ``plan_id``)::

    {
      "type": "subscription.created" | "subscription.updated" | ...,
      "id": "<uuid>",
      "data": {
        "customer_id": "<dhanam-side customer id — NOT a Stripe customer id>",
        "subscription_id": "<upstream subscription id, may be absent>",
        "plan_id": "selva_team",
        "organization_id": "<selva org id, from checkout metadata.orgId>",
        "status": "<event-type suffix: 'created' / 'updated' / ...>"
      },
      "timestamp": "<ISO-8601>"
    }

Payment events (``payment.succeeded`` / ``payment.failed`` /
``payment.refunded``) use the ``DhanamPaymentEnvelope`` shape
(``apps/api/src/modules/billing/services/stripe-mx-spei-relay.service.ts:138-194``)
and FAN OUT to every configured consumer — Selva receives them for other
products' sales too. They carry no ``organization_id``, so this reader
acknowledges them without applying state.

Reader doctrine (this repo's read-proof rule): "read nothing" must never look
like "read everything and found nothing wrong". Canonical field names apply
state; legacy/alternate names apply state WITH a counted warning; an envelope
that parses but matches no known shape raises
:class:`UnrecognizedDhanamEnvelopeError` so the webhook route can return a
non-2xx and Dhanam's DLQ/telemetry sees the rejection instead of a false 200.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..billing_tiers import DEFAULT_TIER, get_daily_limit, is_valid_subscription_tier
from ..config import get_settings
from ..database import tenant_session
from ..models import TenantConfig
from .checkout_tiers import (
    SELVA_PRODUCT_SLUG,
    pricing_slug_for_catalog_tier,
    tier_for_plan_id,
)

logger = logging.getLogger(__name__)

try:  # Same optional-dependency guard as nexus_api.operational_metrics.
    from prometheus_client import Counter

    DHANAM_ENVELOPE_ANOMALIES = Counter(
        "selva_dhanam_webhook_envelope_anomalies_total",
        "Dhanam billing webhook envelopes that needed legacy-field tolerance "
        "or were rejected as unrecognized, by event type and reason.",
        ["event_type", "reason"],
    )
    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _HAS_PROMETHEUS = False


def _count_envelope_anomaly(event_type: str, reason: str) -> None:
    """Increment the anomaly counter (label-safe, best-effort)."""
    if not _HAS_PROMETHEUS:
        return
    try:
        # Dhanam signs every payload we count, but keep label cardinality
        # bounded anyway: the event type is truncated, the reason is ours.
        DHANAM_ENVELOPE_ANOMALIES.labels(event_type[:64] or "unknown", reason).inc()
    except Exception:  # pragma: no cover - metrics must never break billing
        logger.debug("Failed to count Dhanam envelope anomaly", exc_info=True)


class UnrecognizedDhanamEnvelopeError(ValueError):
    """A signed Dhanam envelope parsed but matched no shape this reader knows.

    Raised instead of silently acknowledging so the webhook route can return
    a non-2xx: Dhanam's product-webhook dispatcher persists non-2xx responses
    to its DLQ (bounded retries, then parked exhausted), which is exactly the
    upstream-visible failure signal a silently dropped envelope never gets.
    """

    def __init__(self, reason: str, event_type: str) -> None:
        super().__init__(f"unrecognized Dhanam envelope ({reason}) for type={event_type}")
        self.reason = reason
        self.event_type = event_type


#: Event types that apply subscription state (tier upgrade path).
_SUBSCRIPTION_APPLY_EVENTS = frozenset({"subscription.created", "subscription.updated"})

#: Event types that mark a subscription cancelled. Note: as of 2026-07-28
#: Dhanam's dispatcher never actually emits these to product webhooks (the
#: cancel paths pass an empty plan id, which its per-product router drops),
#: but the reader must stay correct if that gap is fixed upstream.
_SUBSCRIPTION_CANCEL_EVENTS = frozenset({"subscription.cancelled", "subscription.deleted"})

#: Payment-envelope fan-out (stripe-mx SPEI relay + Conekta relay). Delivered
#: to ALL configured consumers regardless of product; carries no org
#: attribution, so acknowledging without side effects is the correct read.
_PAYMENT_FANOUT_EVENTS = frozenset(
    {"payment.succeeded", "payment.failed", "payment.refunded"}
)

#: Legacy invoice vocabulary from this handler's original (imagined) contract.
#: Dhanam's product-webhook surface has never emitted these, but they remain
#: handled so an intentional future emitter does not regress overage clearing.
_LEGACY_INVOICE_EVENTS = frozenset({"invoice.paid", "invoice.payment_failed"})


async def cache_tier_limit(org_id: str, tier: str) -> None:
    """Mirror tier daily limit into Redis for dispatch budget checks."""
    daily_limit = get_daily_limit(tier)
    try:
        from selva_redis_pool import get_redis_pool

        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        await pool.execute_with_retry(
            "set", f"selva:tier:{org_id}", str(daily_limit), ex=86400
        )
    except Exception:
        logger.warning(
            "Failed to cache tier limit for org=%s tier=%s in Redis",
            org_id,
            tier,
            exc_info=True,
        )


async def clear_overage_counter(org_id: str) -> None:
    """Clear daily overage counter after successful invoice payment."""
    try:
        from selva_redis_pool import get_redis_pool

        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        await pool.execute_with_retry("delete", f"selva:tier_overage:{org_id}")
    except Exception:
        logger.warning(
            "Failed to clear tier_overage Redis key for org=%s",
            org_id,
            exc_info=True,
        )


def _parse_period_end(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _normalize_tier(raw: Any) -> str:
    tier = str(raw or DEFAULT_TIER).strip().lower()
    return tier or DEFAULT_TIER


async def resolve_tenant_by_org_id(db: AsyncSession, org_id: str) -> TenantConfig | None:
    if not org_id:
        return None
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    return result.scalar_one_or_none()


async def apply_subscription_state(
    db: AsyncSession,
    *,
    org_id: str,
    tier: str,
    status: str,
    current_period_end: datetime | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    dhanam_space_id: str | None = None,
) -> TenantConfig | None:
    """Update tenant_configs from a Dhanam-normalized subscription event."""
    tenant = await resolve_tenant_by_org_id(db, org_id)
    if tenant is None:
        return None

    tenant.subscription_tier = _normalize_tier(tier)
    tenant.subscription_status = status
    if current_period_end is not None:
        tenant.subscription_current_period_end = current_period_end
    if stripe_customer_id:
        tenant.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        tenant.stripe_subscription_id = stripe_subscription_id
    if dhanam_space_id:
        tenant.dhanam_space_id = dhanam_space_id

    await db.commit()
    await cache_tier_limit(org_id, tenant.subscription_tier)
    return tenant


async def mark_subscription_cancelled(
    db: AsyncSession,
    *,
    org_id: str,
    current_period_end: datetime | None = None,
) -> TenantConfig | None:
    tenant = await resolve_tenant_by_org_id(db, org_id)
    if tenant is None:
        return None
    tenant.subscription_status = "cancelled"
    if current_period_end is not None:
        tenant.subscription_current_period_end = current_period_end
    await db.commit()
    return tenant


async def emit_billing_task_event(
    db: AsyncSession,
    *,
    org_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    from ..routers.events import emit_event_db

    await emit_event_db(
        db,
        event_type=event_type,
        event_category="billing",
        org_id=org_id,
        payload=payload,
    )
    await db.commit()


def _resolve_envelope_org_id(event_type: str, data: dict[str, Any]) -> str:
    """Resolve the Selva org id from a Dhanam envelope, canonical name first.

    Canonical: ``data.organization_id`` — the field Dhanam's dispatcher emits
    (propagated from checkout ``metadata.orgId``). Tolerated with a counted
    warning: the legacy ``data.org_id`` this reader used to require, and a
    nested ``data.metadata.orgId`` as a defensive last resort. Returns ``""``
    when nothing resolves; the caller decides how loud that is.
    """
    canonical = str(data.get("organization_id") or "").strip()
    if canonical:
        return canonical

    legacy = str(data.get("org_id") or "").strip()
    if legacy:
        logger.warning(
            "dhanam_envelope_legacy_field: type=%s carried org under legacy "
            "'org_id' instead of canonical 'organization_id'; accepted, but "
            "the sender should be updated",
            event_type,
        )
        _count_envelope_anomaly(event_type, "legacy_org_field")
        return legacy

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        nested = str(metadata.get("orgId") or metadata.get("org_id") or "").strip()
        if nested:
            logger.warning(
                "dhanam_envelope_metadata_org_fallback: type=%s resolved org "
                "from data.metadata instead of canonical 'organization_id'",
                event_type,
            )
            _count_envelope_anomaly(event_type, "metadata_org_fallback")
            return nested

    return ""


def _resolve_envelope_tier(
    event_type: str, data: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Resolve the Selva tier from a Dhanam envelope.

    Returns ``(tier, foreign_plan)``:

    - ``(tier, None)``  — a Selva tier resolved. Canonical source is
      ``data.plan_id`` (``selva_team`` → catalog tier ``team`` → pricing slug
      ``professional``); the legacy bare ``data.tier`` field is tolerated with
      a counted warning.
    - ``(None, plan)``  — ``plan_id`` belongs to another product (misrouted
      fan-out / upstream routing change); nothing to apply here.
    - ``(None, None)``  — no tier information at all.
    """
    plan_id = str(data.get("plan_id") or "").strip().lower()
    if plan_id:
        catalog_tier = tier_for_plan_id(plan_id)
        if catalog_tier is None and plan_id != SELVA_PRODUCT_SLUG:
            return None, plan_id
        if catalog_tier is None:
            # Bare "selva" plan id: addressed to us, but carries no tier.
            return None, None
        tier = pricing_slug_for_catalog_tier(catalog_tier)
        if not is_valid_subscription_tier(tier):
            logger.warning(
                "dhanam_envelope_unknown_tier: type=%s plan_id=%s resolved to "
                "tier %r which has no configured daily limit; storing it "
                "as-is (limit lookups fall back to the default tier)",
                event_type,
                plan_id,
                tier,
            )
            _count_envelope_anomaly(event_type, "unknown_tier")
        return tier, None

    legacy_tier = str(data.get("tier") or "").strip().lower()
    if legacy_tier:
        logger.warning(
            "dhanam_envelope_legacy_field: type=%s carried tier under legacy "
            "'tier' instead of canonical 'plan_id'; accepted, but the sender "
            "should be updated",
            event_type,
        )
        _count_envelope_anomaly(event_type, "legacy_tier_field")
        return pricing_slug_for_catalog_tier(legacy_tier), None

    return None, None


def _normalize_subscription_status(raw: Any) -> str:
    """Project Dhanam's envelope ``status`` onto Selva's status vocabulary.

    In the canonical envelope ``data.status`` is just the event-type suffix
    (``created`` / ``updated``), not a subscription lifecycle status — map
    those to ``active`` so dispatch gating (``subscription_blocks_dispatch``)
    keeps meaning. Any other value (e.g. a future real ``past_due``) passes
    through lowercased.
    """
    status = str(raw or "").strip().lower()
    if status in {"", "created", "updated", "active"}:
        return "active"
    return status


async def handle_dhanam_billing_event(payload: dict[str, Any]) -> None:
    """Process a signed Dhanam billing webhook (canonical POS/Stripe router).

    Raises :class:`UnrecognizedDhanamEnvelopeError` when the envelope parses
    but matches no shape this reader knows how to apply — the route turns
    that into a non-2xx so Dhanam's retry/DLQ telemetry records the miss.
    """
    event_type = str(payload.get("type") or "unknown")
    data_raw = payload.get("data")
    data: dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}

    # Payment fan-out envelopes are addressed to every consumer and carry no
    # org attribution: acknowledging them IS the correct full read. Log with
    # a stable marker so "acknowledged deliberately" is distinguishable from
    # "never arrived" without implying an anomaly.
    if event_type in _PAYMENT_FANOUT_EVENTS:
        logger.info(
            "dhanam_payment_event_acknowledged: type=%s envelope=%s plan_id=%s "
            "(payment fan-out carries no organization_id; no state to apply)",
            event_type,
            payload.get("id"),
            data.get("plan_id"),
        )
        return

    known_event = (
        event_type in _SUBSCRIPTION_APPLY_EVENTS
        or event_type in _SUBSCRIPTION_CANCEL_EVENTS
        or event_type in _LEGACY_INVOICE_EVENTS
    )
    if not known_event:
        logger.error(
            "dhanam_envelope_unrecognized: type=%s envelope=%s matched no "
            "known shape; rejecting so the sender's retry/telemetry sees it",
            event_type,
            payload.get("id"),
        )
        _count_envelope_anomaly(event_type, "unknown_event_type")
        raise UnrecognizedDhanamEnvelopeError("unknown_event_type", event_type)

    org_id = _resolve_envelope_org_id(event_type, data)

    tier: str | None = None
    if event_type in _SUBSCRIPTION_APPLY_EVENTS:
        tier, foreign_plan = _resolve_envelope_tier(event_type, data)
        if foreign_plan is not None:
            # Another product's plan reaching this endpoint means upstream
            # routing surprised us. Deliberately NOT applied and NOT an
            # error response: retrying an authentic-but-foreign envelope
            # cannot change the outcome.
            logger.warning(
                "dhanam_envelope_foreign_plan: type=%s plan_id=%s is not a "
                "%s plan; acknowledged without applying state",
                event_type,
                foreign_plan,
                SELVA_PRODUCT_SLUG,
            )
            _count_envelope_anomaly(event_type, "foreign_plan")
            return
        if tier is None:
            logger.error(
                "dhanam_envelope_unrecognized: type=%s envelope=%s carries no "
                "resolvable tier (no plan_id/tier field); rejecting",
                event_type,
                payload.get("id"),
            )
            _count_envelope_anomaly(event_type, "missing_tier")
            raise UnrecognizedDhanamEnvelopeError("missing_tier", event_type)

    if not org_id:
        # Known event type addressed to nobody — e.g. the upstream path that
        # dispatches subscription.updated with an empty organization_id. The
        # paid state CANNOT be applied; a silent 200 here is exactly the
        # "read nothing, reported nothing wrong" failure mode.
        logger.error(
            "dhanam_envelope_unrecognized: type=%s envelope=%s has no "
            "resolvable organization (organization_id/org_id/metadata.orgId "
            "all absent or empty); rejecting",
            event_type,
            payload.get("id"),
        )
        _count_envelope_anomaly(event_type, "missing_org")
        raise UnrecognizedDhanamEnvelopeError("missing_org", event_type)

    status = _normalize_subscription_status(data.get("status"))
    period_end = _parse_period_end(data.get("current_period_end"))
    # Legacy external-reference names, kept for tolerance. The canonical
    # envelope's `customer_id` is a Dhanam-side customer id, NOT a Stripe
    # customer id, so it is deliberately never written to stripe_customer_id.
    stripe_customer_id = data.get("external_customer_id") or data.get("stripe_customer_id")
    # Canonical `subscription_id` is the upstream subscription reference
    # (Stripe subscription id on the live Stripe-relay path); legacy names
    # remain accepted.
    stripe_subscription_id = (
        data.get("subscription_id")
        or data.get("external_subscription_id")
        or data.get("stripe_subscription_id")
    )
    dhanam_space_id = data.get("dhanam_space_id")

    async with tenant_session(org_id=org_id) as db:
        if event_type in _SUBSCRIPTION_APPLY_EVENTS:
            assert tier is not None  # narrowed above; mypy aid
            tenant = await apply_subscription_state(
                db,
                org_id=org_id,
                tier=tier,
                status=status,
                current_period_end=period_end,
                stripe_customer_id=str(stripe_customer_id) if stripe_customer_id else None,
                stripe_subscription_id=str(stripe_subscription_id)
                if stripe_subscription_id
                else None,
                dhanam_space_id=str(dhanam_space_id) if dhanam_space_id else None,
            )
            if tenant is None:
                logger.warning(
                    "dhanam_subscription_unknown_org: %s for org=%s matched no "
                    "tenant; acknowledged without applying state (a retry "
                    "cannot create the org)",
                    event_type,
                    org_id,
                )
                _count_envelope_anomaly(event_type, "unknown_org")
                return
            logger.info(
                "Dhanam %s processed: org=%s tier=%s status=%s",
                event_type,
                org_id,
                tier,
                status,
            )
            return

        if event_type in _SUBSCRIPTION_CANCEL_EVENTS:
            tenant = await mark_subscription_cancelled(
                db, org_id=org_id, current_period_end=period_end
            )
            if tenant is None:
                logger.warning(
                    "dhanam_subscription_unknown_org: %s for org=%s matched no "
                    "tenant; acknowledged without applying state",
                    event_type,
                    org_id,
                )
                _count_envelope_anomaly(event_type, "unknown_org")
                return
            logger.info("Dhanam %s processed: org=%s", event_type, org_id)
            return

        if event_type == "invoice.paid":
            tenant = await resolve_tenant_by_org_id(db, org_id)
            if tenant is None:
                logger.warning(
                    "dhanam_subscription_unknown_org: invoice.paid for org=%s "
                    "matched no tenant; acknowledged without applying state",
                    org_id,
                )
                _count_envelope_anomaly(event_type, "unknown_org")
                return
            if tenant.subscription_status == "past_due":
                tenant.subscription_status = "active"
                await db.commit()
            await emit_billing_task_event(
                db,
                org_id=org_id,
                event_type="billing.invoice_paid",
                payload={
                    "invoice_id": data.get("invoice_id"),
                    "amount_paid": data.get("amount_cents"),
                    "currency": data.get("currency"),
                    "payment_provider": data.get("payment_provider", "dhanam"),
                    "dhanam_space_id": dhanam_space_id,
                },
            )
            await clear_overage_counter(org_id)
            logger.info("Dhanam invoice.paid processed: org=%s", org_id)
            return

        if event_type == "invoice.payment_failed":
            tenant = await resolve_tenant_by_org_id(db, org_id)
            if tenant is None:
                logger.warning(
                    "dhanam_subscription_unknown_org: invoice.payment_failed "
                    "for org=%s matched no tenant; acknowledged without "
                    "applying state",
                    org_id,
                )
                _count_envelope_anomaly(event_type, "unknown_org")
                return
            tenant.subscription_status = "past_due"
            await db.commit()
            await emit_billing_task_event(
                db,
                org_id=org_id,
                event_type="billing.payment_failed",
                payload={
                    "invoice_id": data.get("invoice_id"),
                    "amount_due": data.get("amount_cents"),
                    "currency": data.get("currency"),
                    "payment_provider": data.get("payment_provider", "dhanam"),
                    "next_payment_attempt": data.get("next_payment_attempt"),
                },
            )
            logger.warning("Dhanam invoice.payment_failed processed: org=%s", org_id)
            return
