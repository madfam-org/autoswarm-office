"""Tests for the durable USD inference-usage ledger (RFC 0034 P1)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus_api.services.inference_usage_ledger import record_inference_usage


@pytest.mark.asyncio
async def test_records_org_attributed_usd_priced_entry() -> None:
    added: list = []
    db = MagicMock()
    db.add = added.append
    db.flush = AsyncMock()

    entry = await record_inference_usage(
        db,
        org_id="dhanam",
        caller="service:dhanam-api",
        provider="anthropic",
        model="claude-opus-4",
        prompt_tokens=1000,
        completion_tokens=500,
    )

    assert added == [entry]
    assert entry.action == "inference_proxy"
    assert entry.amount == 1500  # total tokens
    assert entry.org_id == "dhanam"
    assert entry.caller == "service:dhanam-api"
    assert entry.provider == "anthropic"
    # Real provider price, not a flat guess: 1000*15 + 500*75 per 1M = 0.0525.
    assert entry.cost_usd == Decimal("0.0525")
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_cheaper_provider_prices_lower() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    opus = await record_inference_usage(
        db,
        org_id="o",
        caller="c",
        provider="anthropic",
        model="claude-opus-4",
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    cheap = await record_inference_usage(
        db,
        org_id="o",
        caller="c",
        provider="deepinfra",
        model="meta-llama/llama-3.1-70b-instruct",
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    # The whole point of routing to a cheaper provider is a lower ledger cost.
    assert cheap.cost_usd < opus.cost_usd


@pytest.mark.asyncio
async def test_defaults_org_and_caller_when_missing() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    entry = await record_inference_usage(
        db,
        org_id="",
        caller="",
        provider="openai",
        model="gpt-4o",
        prompt_tokens=10,
        completion_tokens=10,
    )
    assert entry.org_id == "platform"
    assert entry.caller == "unknown"


@pytest.mark.asyncio
async def test_negative_tokens_are_floored_not_raised() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    entry = await record_inference_usage(
        db,
        org_id="o",
        caller="c",
        provider="openai",
        model="gpt-4o",
        prompt_tokens=-5,
        completion_tokens=20,
    )
    assert entry.amount == 20  # -5 floored to 0
    assert entry.cost_usd >= Decimal("0")
