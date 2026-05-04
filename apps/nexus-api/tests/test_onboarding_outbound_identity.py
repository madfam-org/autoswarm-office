"""Tests for tenant outbound-identity columns + endpoints (migration 0026).

Closes the regression introduced by the v2.2.x email From: lockdown
(commit b72399e). Verifies:

- ``GET /api/v1/onboarding/tenant-identity`` returns nullable fields
  when the new ``tenant_configs.outbound_*`` columns are unset (legacy
  fallback chain still active).
- GET prefers the new columns when set (regression-fix path).
- ``PUT /api/v1/onboarding/tenant-identity`` requires auth.
- PUT writes the columns and emits a ``tenant_identity.updated`` event
  with ``event_category="onboarding"``.
- PUT validates ``outbound_user_email`` against the email regex.
- PUT validates ``outbound_agent_slug`` against the 5-entry allow-list.
- PUT scopes by JWT ``org_id`` — cross-tenant write attempts cannot
  affect another org's row.
- The ``_AGENT_SLUG_ALLOWLIST`` here mirrors
  ``email_tools._AGENT_ROLE_ALLOWLIST`` (drift guard).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import TaskEvent, TenantConfig, TenantIdentity
from nexus_api.routers.onboarding import _AGENT_SLUG_ALLOWLIST

_TENANTS_URL = "/api/v1/tenants"
_IDENTITY_URL = "/api/v1/onboarding/tenant-identity"


async def _bootstrap_tenant(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        f"{_TENANTS_URL}/",
        headers=headers,
        json={"org_name": "Outbound Identity Test Co"},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# GET /onboarding/tenant-identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_null_fields_when_columns_unset(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """When the new outbound_* columns are NULL and there's no
    tenant_identities row, every resolved field comes back null. This
    is the "fallback path verified" case — the GET path no longer
    crashes when the new columns are missing."""
    await _bootstrap_tenant(client, auth_headers)
    resp = await client.get(_IDENTITY_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # No outbound_user_email column data, no tenant_identities row →
    # legacy primary_contact_email is None, so user_email is None too.
    assert body["user_email"] is None
    # user_name still falls through brand_name / razon_social, both NULL.
    assert body["user_name"] is None
    assert body["org_name"] is None
    # agent_slug is the new optional field.
    assert body["agent_slug"] is None


@pytest.mark.asyncio
async def test_get_prefers_outbound_columns_over_legacy_fallbacks(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """The new outbound_* columns must take precedence over the legacy
    brand_name / razon_social / tenant_identities chain. This is the
    regression-fix: tenants who set outbound_user_email via the office
    UI no longer need MADFAM ops to populate tenant_identities."""
    await _bootstrap_tenant(client, auth_headers)

    # Seed the legacy fallback chain so we can prove the new columns
    # actually win over it.
    tenant = (await db_session.execute(select(TenantConfig))).scalar_one()
    tenant.brand_name = "Legacy Brand"
    tenant.razon_social = "Legacy Razon S.A. de C.V."
    db_session.add(
        TenantIdentity(
            canonical_id=tenant.org_id,
            legal_name="Legacy Legal Name S.A.",
            primary_contact_email="legacy@example.com",
        )
    )
    # Now seed the new first-class columns.
    tenant.outbound_user_email = "outbound@tenant.example"
    tenant.outbound_user_name = "Tenant Outbound Name"
    tenant.outbound_agent_slug = "sales"
    await db_session.commit()

    resp = await client.get(_IDENTITY_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # New columns win for user_email + user_name + agent_slug.
    assert body["user_email"] == "outbound@tenant.example"
    assert body["user_name"] == "Tenant Outbound Name"
    assert body["agent_slug"] == "sales"
    # org_name is still resolved via the legacy chain (legal_name first).
    assert body["org_name"] == "Legacy Legal Name S.A."


@pytest.mark.asyncio
async def test_get_falls_back_to_legacy_when_outbound_columns_null(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """When the new outbound_* columns are NULL but the legacy chain
    is populated, the GET endpoint must still return the legacy
    values. This is the back-compat guarantee for tenants who were
    onboarded before migration 0026."""
    await _bootstrap_tenant(client, auth_headers)
    tenant = (await db_session.execute(select(TenantConfig))).scalar_one()
    tenant.brand_name = "Brand From Legacy"
    db_session.add(
        TenantIdentity(
            canonical_id=tenant.org_id,
            legal_name="Legal From Legacy S.A.",
            primary_contact_email="legacy@tenant.example",
        )
    )
    await db_session.commit()

    resp = await client.get(_IDENTITY_URL, headers=auth_headers)
    body = resp.json()
    # outbound_user_email is NULL → falls through to primary_contact_email.
    assert body["user_email"] == "legacy@tenant.example"
    # outbound_user_name is NULL → falls through to brand_name (highest).
    assert body["user_name"] == "Brand From Legacy"
    # outbound_agent_slug is NULL → returned as null.
    assert body["agent_slug"] is None


# ---------------------------------------------------------------------------
# PUT /onboarding/tenant-identity — auth, audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_requires_auth(client: httpx.AsyncClient) -> None:
    """No Bearer token → 401/403 from the auth dependency."""
    resp = await client.put(
        _IDENTITY_URL,
        json={"outbound_user_email": "anon@example.com"},
    )
    # FastAPI's Depends(get_current_user) raises on missing token.
    # Could be 401 (HTTPBearer unauthorized) or 403 depending on
    # auto_error settings — both are non-success.
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_put_writes_columns_and_emits_audit_event(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Happy path: PUT writes all three columns and emits a
    ``tenant_identity.updated`` event with the changed keys + actor."""
    await _bootstrap_tenant(client, auth_headers)

    resp = await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={
            "outbound_user_email": "ceo@tenant.example",
            "outbound_user_name": "Tenant CEO",
            "outbound_agent_slug": "growth",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_email"] == "ceo@tenant.example"
    assert body["user_name"] == "Tenant CEO"
    assert body["agent_slug"] == "growth"

    # Columns persisted on tenant_configs.
    tenant = (await db_session.execute(select(TenantConfig))).scalar_one()
    assert tenant.outbound_user_email == "ceo@tenant.example"
    assert tenant.outbound_user_name == "Tenant CEO"
    assert tenant.outbound_agent_slug == "growth"

    # Audit event landed in task_events with event_category="onboarding".
    events = (
        (
            await db_session.execute(
                select(TaskEvent).where(TaskEvent.event_type == "tenant_identity.updated")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.event_category == "onboarding"
    payload = event.payload or {}
    assert sorted(payload.get("changed_keys", [])) == [
        "outbound_agent_slug",
        "outbound_user_email",
        "outbound_user_name",
    ]
    # Actor identity captured for the audit trail (dev-bypass user).
    assert payload.get("actor_sub")


@pytest.mark.asyncio
async def test_put_no_op_when_values_unchanged(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Submitting the same values that are already stored should NOT
    emit a duplicate audit event — saves log noise + audit-row spam."""
    await _bootstrap_tenant(client, auth_headers)
    # First write
    await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": "stable@tenant.example"},
    )
    # Second write of same value
    await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": "stable@tenant.example"},
    )
    events = (
        (
            await db_session.execute(
                select(TaskEvent).where(TaskEvent.event_type == "tenant_identity.updated")
            )
        )
        .scalars()
        .all()
    )
    # Only the first PUT should have produced an audit event.
    assert len(events) == 1


# ---------------------------------------------------------------------------
# PUT /onboarding/tenant-identity — validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_rejects_invalid_email_format(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """``outbound_user_email`` must match ``[^@\\s]+@[^@\\s]+\\.[^@\\s]+``
    (same regex used by SendEmailTool's recipient validation)."""
    await _bootstrap_tenant(client, auth_headers)
    resp = await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": "not-an-email"},
    )
    # Pydantic field_validator → 422.
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "outbound_user_email" in str(detail)


@pytest.mark.asyncio
async def test_put_rejects_unknown_agent_slug(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """``outbound_agent_slug`` must be one of the 5 allow-list entries.
    Mirrors the ``email_tools._AGENT_ROLE_ALLOWLIST`` constraint."""
    await _bootstrap_tenant(client, auth_headers)
    resp = await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_agent_slug": "marketing"},  # not in the allow-list
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "outbound_agent_slug" in str(detail)


@pytest.mark.asyncio
async def test_put_accepts_each_allow_list_slug(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """All 5 entries in the allow-list must round-trip through PUT."""
    await _bootstrap_tenant(client, auth_headers)
    for slug in _AGENT_SLUG_ALLOWLIST:
        resp = await client.put(
            _IDENTITY_URL,
            headers=auth_headers,
            json={"outbound_agent_slug": slug},
        )
        assert resp.status_code == 200, f"{slug} failed: {resp.text}"
        assert resp.json()["agent_slug"] == slug


@pytest.mark.asyncio
async def test_put_clears_field_when_null_submitted(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Submitting ``null`` clears the column — the legacy fallback
    chain takes over on the next read."""
    await _bootstrap_tenant(client, auth_headers)
    # Set then clear
    await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": "first@tenant.example"},
    )
    await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": None},
    )
    tenant = (await db_session.execute(select(TenantConfig))).scalar_one()
    assert tenant.outbound_user_email is None


# ---------------------------------------------------------------------------
# PUT /onboarding/tenant-identity — tenant scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_scopes_writes_to_jwt_org_id(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A PUT writes only the JWT-scoped tenant's row — even if the
    request body or path contained another org_id, it would be
    ignored. Verifies the no-cross-tenant-write invariant."""
    await _bootstrap_tenant(client, auth_headers)
    # Add a SEPARATE second tenant directly via the DB so we can prove
    # the PUT didn't reach across orgs.
    db_session.add(
        TenantConfig(
            org_id="other-tenant-org",
            outbound_user_email="other@other.example",
        )
    )
    await db_session.commit()

    # PUT under the dev-org JWT context.
    resp = await client.put(
        _IDENTITY_URL,
        headers=auth_headers,
        json={"outbound_user_email": "ours@tenant.example"},
    )
    assert resp.status_code == 200, resp.text

    # Our org_id row was updated.
    own = (
        await db_session.execute(select(TenantConfig).where(TenantConfig.org_id == "dev-org"))
    ).scalar_one()
    assert own.outbound_user_email == "ours@tenant.example"

    # The OTHER tenant's row is untouched.
    await db_session.refresh(
        (
            await db_session.execute(
                select(TenantConfig).where(TenantConfig.org_id == "other-tenant-org")
            )
        ).scalar_one()
    )
    other = (
        await db_session.execute(
            select(TenantConfig).where(TenantConfig.org_id == "other-tenant-org")
        )
    ).scalar_one()
    assert other.outbound_user_email == "other@other.example"  # unchanged


# ---------------------------------------------------------------------------
# Drift guard — keep email_tools allow-list in sync.
# ---------------------------------------------------------------------------


def test_agent_slug_allowlist_in_sync_with_email_tools() -> None:
    """``onboarding._AGENT_SLUG_ALLOWLIST`` must mirror
    ``email_tools._AGENT_ROLE_ALLOWLIST`` keys. Drift here means the
    UI lets a tenant pin a slug that the email tool will then reject
    at send-time — silent breakage."""
    from selva_tools.builtins.email_tools import _AGENT_ROLE_ALLOWLIST

    assert _AGENT_SLUG_ALLOWLIST == frozenset(_AGENT_ROLE_ALLOWLIST.keys())
