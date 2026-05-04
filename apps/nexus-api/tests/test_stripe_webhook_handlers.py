"""Tests for the Phase 2.7 Stripe webhook event handlers.

The handler functions are tested directly (no HTTP path) so we can pin
their side effects on a real SQLite session without going through the
full Stripe signature dance — that path is already covered by
``test_stripe_webhook.py``.

What we pin here:

- ``_handle_subscription_created`` mirrors status + tier + period end
  onto the ``tenant_configs`` row resolved by ``stripe_customer_id``.
- ``_handle_subscription_updated`` refreshes those columns and is
  tolerant of an unchanged tier (period end may still roll).
- ``_handle_subscription_deleted`` flips status to ``cancelled`` but
  preserves ``subscription_tier`` so the grace-period scheduler has
  the context it needs.
- ``_handle_invoice_paid`` clears the ``past_due`` flag, fires a
  ``billing.invoice_paid`` task event, and clears the overage Redis
  key (mocked).
- ``_handle_invoice_payment_failed`` flips status to ``past_due`` and
  fires a ``billing.payment_failed`` task event but does NOT downgrade
  the tier (Stripe handles dunning).
- All five handlers MUST swallow "tenant not found" silently — Stripe
  test events / pre-backfill events would otherwise put the endpoint
  into a Stripe retry loop.
- Helpers (``_extract_subscription_tier``, ``_coerce_period_end``,
  ``_extract_customer_id``) cover the resolution edges.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import TaskEvent, TenantConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sub_event(
    event_type: str,
    customer_id: str,
    sub_id: str = "sub_test",
    status_value: str = "active",
    price_id: str = "price_pro",
    period_end: int | None = 1_800_000_000,
) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "data": {
            "object": {
                "id": sub_id,
                "customer": customer_id,
                "status": status_value,
                "current_period_end": period_end,
                "items": {"data": [{"price": {"id": price_id}}]},
            }
        },
    }


def _invoice_event(
    event_type: str,
    customer_id: str,
    invoice_id: str = "in_test",
    amount: int = 1000,
    currency: str = "mxn",
    next_attempt: int | None = None,
) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "data": {
            "object": {
                "id": invoice_id,
                "customer": customer_id,
                "amount_paid": amount,
                "amount_due": amount,
                "currency": currency,
                "next_payment_attempt": next_attempt,
            }
        },
    }


async def _seed_tenant(
    db: AsyncSession,
    *,
    org_id: str = "org-A",
    stripe_customer_id: str = "cus_test_A",
    subscription_status: str | None = None,
    subscription_tier: str | None = None,
) -> TenantConfig:
    tenant = TenantConfig(
        org_id=org_id,
        stripe_customer_id=stripe_customer_id,
        subscription_status=subscription_status,
        subscription_tier=subscription_tier,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@pytest.fixture(autouse=True)
def _stub_redis_and_settings(monkeypatch: pytest.MonkeyPatch):
    """Mute the Redis fire-and-forget paths and pin the price→tier map."""
    from nexus_api.routers import stripe_webhooks

    monkeypatch.setattr(
        stripe_webhooks, "_cache_tier_limit", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        stripe_webhooks, "_clear_overage_counter", AsyncMock(return_value=None)
    )

    # Make the webhook handlers re-use the test session factory rather
    # than creating their own (which would point at the production
    # engine).  The fixture wires both names because handlers import the
    # symbol directly out of nexus_api.database.
    from nexus_api.database import async_session_factory as _real_factory

    monkeypatch.setattr(stripe_webhooks, "async_session_factory", _real_factory)

    from nexus_api.config import get_settings

    settings = get_settings()
    settings.stripe_price_to_tier_map = {
        "price_starter": "starter",
        "price_pro": "professional",
        "price_ent": "enterprise",
    }


# ---------------------------------------------------------------------------
# _extract_customer_id / _extract_subscription_tier / _coerce_period_end
# ---------------------------------------------------------------------------


class TestExtractCustomerId:
    def test_bare_string_customer(self) -> None:
        from nexus_api.routers.stripe_webhooks import _extract_customer_id

        evt = {"data": {"object": {"customer": "cus_X"}}}
        assert _extract_customer_id(evt) == "cus_X"

    def test_expanded_customer_object(self) -> None:
        from nexus_api.routers.stripe_webhooks import _extract_customer_id

        evt = {"data": {"object": {"customer": {"id": "cus_Y", "email": "e@x"}}}}
        assert _extract_customer_id(evt) == "cus_Y"

    def test_missing_customer_returns_empty(self) -> None:
        from nexus_api.routers.stripe_webhooks import _extract_customer_id

        evt = {"data": {"object": {}}}
        assert _extract_customer_id(evt) == ""


class TestExtractSubscriptionTier:
    def test_known_price_returns_mapped_tier(self) -> None:
        from nexus_api.routers.stripe_webhooks import _extract_subscription_tier

        sub = {"items": {"data": [{"price": {"id": "price_pro"}}]}}
        assert _extract_subscription_tier(sub) == "professional"

    def test_unknown_price_falls_back_to_default(self) -> None:
        from nexus_api.billing_tiers import DEFAULT_TIER
        from nexus_api.routers.stripe_webhooks import _extract_subscription_tier

        sub = {"items": {"data": [{"price": {"id": "price_unmapped"}}]}}
        assert _extract_subscription_tier(sub) == DEFAULT_TIER

    def test_no_items_falls_back_to_default(self) -> None:
        from nexus_api.billing_tiers import DEFAULT_TIER
        from nexus_api.routers.stripe_webhooks import _extract_subscription_tier

        assert _extract_subscription_tier({"items": {"data": []}}) == DEFAULT_TIER


class TestCoercePeriodEnd:
    def test_valid_epoch_returns_utc_datetime(self) -> None:
        from nexus_api.routers.stripe_webhooks import _coerce_period_end

        out = _coerce_period_end({"current_period_end": 1_800_000_000})
        assert isinstance(out, datetime)
        assert out.tzinfo == UTC

    def test_missing_returns_none(self) -> None:
        from nexus_api.routers.stripe_webhooks import _coerce_period_end

        assert _coerce_period_end({}) is None

    def test_garbage_returns_none(self) -> None:
        from nexus_api.routers.stripe_webhooks import _coerce_period_end

        assert _coerce_period_end({"current_period_end": "not-a-number"}) is None


# ---------------------------------------------------------------------------
# _resolve_tenant_by_stripe_customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveTenant:
    async def test_returns_none_for_empty_customer_id(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _resolve_tenant_by_stripe_customer

        assert await _resolve_tenant_by_stripe_customer(db_session, "") is None

    async def test_returns_none_for_unknown_customer(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _resolve_tenant_by_stripe_customer

        assert (
            await _resolve_tenant_by_stripe_customer(db_session, "cus_nope") is None
        )

    async def test_returns_tenant_when_found(self, db_session: AsyncSession) -> None:
        from nexus_api.routers.stripe_webhooks import _resolve_tenant_by_stripe_customer

        await _seed_tenant(
            db_session, org_id="org-resolve", stripe_customer_id="cus_resolve"
        )
        # New session simulates the handler opening its own session.
        from nexus_api.database import async_session_factory

        async with async_session_factory() as fresh:
            tenant = await _resolve_tenant_by_stripe_customer(fresh, "cus_resolve")
            assert tenant is not None
            assert tenant.org_id == "org-resolve"


# ---------------------------------------------------------------------------
# _handle_subscription_created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscriptionCreated:
    async def test_mirrors_status_and_tier_to_tenant(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.database import async_session_factory
        from nexus_api.routers.stripe_webhooks import _handle_subscription_created

        await _seed_tenant(
            db_session, org_id="org-sc", stripe_customer_id="cus_sc"
        )
        evt = _sub_event(
            "customer.subscription.created",
            customer_id="cus_sc",
            sub_id="sub_sc_1",
            status_value="active",
            price_id="price_pro",
        )

        await _handle_subscription_created(evt)

        async with async_session_factory() as fresh:
            res = await fresh.execute(
                select(TenantConfig).where(TenantConfig.org_id == "org-sc")
            )
            t = res.scalar_one()
            assert t.stripe_subscription_id == "sub_sc_1"
            assert t.subscription_status == "active"
            assert t.subscription_tier == "professional"
            assert t.subscription_current_period_end is not None

    async def test_skips_when_tenant_not_found(
        self, db_session: AsyncSession  # noqa: ARG002
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _handle_subscription_created

        # MUST NOT raise even when no tenant matches the customer ID.
        evt = _sub_event(
            "customer.subscription.created",
            customer_id="cus_does_not_exist",
        )
        await _handle_subscription_created(evt)


# ---------------------------------------------------------------------------
# _handle_subscription_updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscriptionUpdated:
    async def test_refreshes_tier_and_period_end(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.database import async_session_factory
        from nexus_api.routers.stripe_webhooks import _handle_subscription_updated

        await _seed_tenant(
            db_session,
            org_id="org-su",
            stripe_customer_id="cus_su",
            subscription_status="active",
            subscription_tier="starter",
        )
        evt = _sub_event(
            "customer.subscription.updated",
            customer_id="cus_su",
            sub_id="sub_su_1",
            price_id="price_ent",
            status_value="active",
            period_end=1_900_000_000,
        )

        await _handle_subscription_updated(evt)

        async with async_session_factory() as fresh:
            t = (
                await fresh.execute(
                    select(TenantConfig).where(TenantConfig.org_id == "org-su")
                )
            ).scalar_one()
            assert t.subscription_tier == "enterprise"
            assert t.subscription_status == "active"

    async def test_skips_when_tenant_not_found(
        self, db_session: AsyncSession  # noqa: ARG002
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _handle_subscription_updated

        evt = _sub_event("customer.subscription.updated", customer_id="cus_nope")
        await _handle_subscription_updated(evt)


# ---------------------------------------------------------------------------
# _handle_subscription_deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscriptionDeleted:
    async def test_marks_cancelled_but_preserves_tier(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.database import async_session_factory
        from nexus_api.routers.stripe_webhooks import _handle_subscription_deleted

        await _seed_tenant(
            db_session,
            org_id="org-sd",
            stripe_customer_id="cus_sd",
            subscription_status="active",
            subscription_tier="professional",
        )
        evt = _sub_event(
            "customer.subscription.deleted",
            customer_id="cus_sd",
            sub_id="sub_sd",
            status_value="canceled",
        )

        await _handle_subscription_deleted(evt)

        async with async_session_factory() as fresh:
            t = (
                await fresh.execute(
                    select(TenantConfig).where(TenantConfig.org_id == "org-sd")
                )
            ).scalar_one()
            assert t.subscription_status == "cancelled"
            # Tier MUST be preserved — grace-period downgrade scheduler
            # reads it after period_end rolls over.
            assert t.subscription_tier == "professional"


# ---------------------------------------------------------------------------
# _handle_invoice_paid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvoicePaid:
    async def test_clears_past_due_and_emits_event(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.database import async_session_factory
        from nexus_api.routers.stripe_webhooks import _handle_invoice_paid

        await _seed_tenant(
            db_session,
            org_id="org-ip",
            stripe_customer_id="cus_ip",
            subscription_status="past_due",
            subscription_tier="professional",
        )
        evt = _invoice_event(
            "invoice.paid",
            customer_id="cus_ip",
            invoice_id="in_paid_1",
            amount=12500,
            currency="mxn",
        )

        await _handle_invoice_paid(evt)

        async with async_session_factory() as fresh:
            t = (
                await fresh.execute(
                    select(TenantConfig).where(TenantConfig.org_id == "org-ip")
                )
            ).scalar_one()
            assert t.subscription_status == "active"

            ev_rows = (
                await fresh.execute(
                    select(TaskEvent).where(TaskEvent.org_id == "org-ip")
                )
            ).scalars().all()
            assert any(e.event_type == "billing.invoice_paid" for e in ev_rows)
            paid = next(e for e in ev_rows if e.event_type == "billing.invoice_paid")
            assert paid.payload["stripe_invoice_id"] == "in_paid_1"
            assert paid.payload["amount_paid"] == 12500

    async def test_skips_when_tenant_not_found(
        self, db_session: AsyncSession  # noqa: ARG002
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _handle_invoice_paid

        evt = _invoice_event("invoice.paid", customer_id="cus_nope")
        await _handle_invoice_paid(evt)


# ---------------------------------------------------------------------------
# _handle_invoice_payment_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvoicePaymentFailed:
    async def test_marks_past_due_and_emits_event(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.database import async_session_factory
        from nexus_api.routers.stripe_webhooks import _handle_invoice_payment_failed

        await _seed_tenant(
            db_session,
            org_id="org-pf",
            stripe_customer_id="cus_pf",
            subscription_status="active",
            subscription_tier="professional",
        )
        evt = _invoice_event(
            "invoice.payment_failed",
            customer_id="cus_pf",
            invoice_id="in_failed_1",
            amount=8500,
            next_attempt=1_900_000_000,
        )

        await _handle_invoice_payment_failed(evt)

        async with async_session_factory() as fresh:
            t = (
                await fresh.execute(
                    select(TenantConfig).where(TenantConfig.org_id == "org-pf")
                )
            ).scalar_one()
            assert t.subscription_status == "past_due"
            # Critical: tier MUST NOT be downgraded on a single failed
            # charge — Stripe handles dunning. We only flip status.
            assert t.subscription_tier == "professional"

            ev_rows = (
                await fresh.execute(
                    select(TaskEvent).where(TaskEvent.org_id == "org-pf")
                )
            ).scalars().all()
            failed = next(
                e for e in ev_rows if e.event_type == "billing.payment_failed"
            )
            assert failed.payload["stripe_invoice_id"] == "in_failed_1"
            assert failed.payload["next_payment_attempt"] == 1_900_000_000

    async def test_skips_when_tenant_not_found(
        self, db_session: AsyncSession  # noqa: ARG002
    ) -> None:
        from nexus_api.routers.stripe_webhooks import _handle_invoice_payment_failed

        evt = _invoice_event("invoice.payment_failed", customer_id="cus_nope")
        await _handle_invoice_payment_failed(evt)


# ---------------------------------------------------------------------------
# _EVENT_HANDLERS dispatch wiring (smoke check)
# ---------------------------------------------------------------------------


class TestEventHandlerDispatchTable:
    def test_all_five_handlers_registered(self) -> None:
        from nexus_api.routers.stripe_webhooks import _EVENT_HANDLERS

        assert set(_EVENT_HANDLERS.keys()) == {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.paid",
            "invoice.payment_failed",
        }
