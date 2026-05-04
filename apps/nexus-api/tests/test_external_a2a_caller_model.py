"""Schema-scaffold smoke tests for the ExternalA2ACaller model.

Phase A of RFC 0018 — A2A external-tenant model. This file pins the
shape of the new ``external_a2a_callers`` table:

- A row can be inserted with the documented column set.
- A row can be read back by ``agent_card_url``.
- The UNIQUE constraint on ``agent_card_url`` is enforced.
- The status / tier / daily_task_limit defaults match the RFC.

These are deliberately **schema-only** tests. The bridge functions
in ``main.py`` still use ``tenant_session(org_id="a2a-external")``
and write SwarmTasks under the synthetic org. Behavior tests for
the per-caller dispatch path land with the cutover PR (Phase C).

The CHECK constraint pinning ``status`` to
``{'active', 'suspended', 'revoked'}`` is enforced by Postgres
(via the migration) but **not** by SQLite (the test backend), so
we do not assert on it here. A Postgres-only integration test will
land alongside the cutover PR.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_create_and_read_back_external_a2a_caller(db_session) -> None:  # noqa: ARG001
    """Happy path: insert a row with the documented columns, read it back."""
    from nexus_api.database import async_session_factory
    from nexus_api.models import ExternalA2ACaller

    async with async_session_factory() as session:
        caller = ExternalA2ACaller(
            name="Test Peer",
            agent_card_url="https://peer.example.com/.well-known/agent.json",
            public_key="-----BEGIN PUBLIC KEY-----\nMOCK\n-----END PUBLIC KEY-----",
            owner_user_id="user-madfam-001",
        )
        session.add(caller)
        await session.commit()
        caller_id = caller.id

    async with async_session_factory() as fresh:
        row = (
            await fresh.execute(
                select(ExternalA2ACaller).where(ExternalA2ACaller.id == caller_id)
            )
        ).scalar_one()

        # Column shape contract.
        assert row.name == "Test Peer"
        assert row.agent_card_url == "https://peer.example.com/.well-known/agent.json"
        assert row.public_key.startswith("-----BEGIN PUBLIC KEY-----")
        # Defaults from the model definition.
        assert row.status == "active"
        assert row.subscription_tier == "external_a2a"
        assert row.daily_task_limit == 100
        # Provenance fields.
        assert row.owner_user_id == "user-madfam-001"
        assert row.created_at is not None
        # last_seen_at is NULL until the cutover PR starts touching it.
        assert row.last_seen_at is None
        # PK is a UUID.
        assert isinstance(row.id, uuid.UUID)


@pytest.mark.asyncio
async def test_unique_agent_card_url_constraint(db_session) -> None:  # noqa: ARG001
    """Two rows with the same ``agent_card_url`` MUST fail at the DB level.

    This is the load-bearing invariant for deterministic per-caller
    org_id derivation: ``org_id = "a2a:" + sha256(agent_card_url)[:16]``.
    If duplicates were allowed, two rows would map to the same org_id
    and the audit trail would conflate them.
    """
    from nexus_api.database import async_session_factory
    from nexus_api.models import ExternalA2ACaller

    async with async_session_factory() as session:
        session.add(
            ExternalA2ACaller(
                name="First",
                agent_card_url="https://dup.example.com/.well-known/agent.json",
            )
        )
        await session.commit()

    with pytest.raises(IntegrityError):
        async with async_session_factory() as session:
            session.add(
                ExternalA2ACaller(
                    name="Second (duplicate URL)",
                    agent_card_url="https://dup.example.com/.well-known/agent.json",
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_minimum_required_columns(db_session) -> None:  # noqa: ARG001
    """A row with only ``name`` + ``agent_card_url`` MUST commit cleanly.

    Pins the contract that ``public_key``, ``owner_user_id``, and
    ``last_seen_at`` are nullable — the registration flow inserts a
    row before the peer has uploaded a key, and the seed row inserted
    by ops has no owner_user_id.
    """
    from nexus_api.database import async_session_factory
    from nexus_api.models import ExternalA2ACaller

    async with async_session_factory() as session:
        caller = ExternalA2ACaller(
            name="Minimal",
            agent_card_url="https://minimal.example.com/.well-known/agent.json",
        )
        session.add(caller)
        await session.commit()
        assert caller.id is not None
        assert caller.public_key is None
        assert caller.owner_user_id is None
        assert caller.last_seen_at is None


@pytest.mark.asyncio
async def test_status_field_accepts_documented_values(db_session) -> None:  # noqa: ARG001
    """All three documented status values round-trip cleanly.

    The DB-level CHECK constraint pinning the value set is Postgres-
    only (see migration 0029); under SQLite the column is plain
    VARCHAR(16) so this test only verifies the documented values
    work — it does NOT assert that an arbitrary string is rejected.
    """
    from nexus_api.database import async_session_factory
    from nexus_api.models import ExternalA2ACaller

    for i, status in enumerate(("active", "suspended", "revoked")):
        async with async_session_factory() as session:
            session.add(
                ExternalA2ACaller(
                    name=f"Caller-{status}",
                    agent_card_url=f"https://status-{i}.example.com/.well-known/agent.json",
                    status=status,
                )
            )
            await session.commit()

    async with async_session_factory() as fresh:
        rows = (
            await fresh.execute(
                select(ExternalA2ACaller).order_by(ExternalA2ACaller.created_at)
            )
        ).scalars().all()
        statuses = sorted(r.status for r in rows)
        assert statuses == ["active", "revoked", "suspended"]
