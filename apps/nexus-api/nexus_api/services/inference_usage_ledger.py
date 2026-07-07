"""Durable, USD-priced inference-usage ledger (RFC 0034 P1).

Before this, the inference proxy metered LLM calls only as best-effort
`task_events` rows (fire-and-forget, 2s timeout, silently dropped on failure)
and never wrote the billing ledger (`ComputeTokenLedger`). Proxy spend was
therefore invisible to the budget/metrics path, token-only, and un-attributed
per product — so per-product AI margin was unknowable.

`record_inference_usage` closes that: it writes one durable ledger row per
call, priced in USD via the shared cost model, attributed to the org and the
calling service/product. The activity-stream event is kept separately (it
stays the observability record); THIS is the source of truth the budget and
metrics paths read.

Fail-safe, not fail-open: a write failure is logged at WARNING and re-raised to
the caller's own error handling — never silently swallowed like the old event
emit. The proxy wraps the call so a ledger hiccup degrades to "spend not
recorded for this call" (logged), never a dropped-and-forgotten write.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from madfam_budget_gate.cost_model import estimate_cost

from ..models import ComputeTokenLedger

logger = logging.getLogger(__name__)


async def record_inference_usage(
    db: AsyncSession,
    *,
    org_id: str,
    caller: str,
    provider: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> ComputeTokenLedger:
    """Write one durable, USD-priced ledger entry for an inference-proxy call.

    `amount` is total tokens (keeps the existing token-budget semantics);
    `cost_usd` is the real provider-priced dollar cost. Returns the entry
    (not yet committed — the caller owns the transaction).
    """
    total_tokens = max(0, prompt_tokens) + max(0, completion_tokens)
    cost_usd = Decimal(
        str(estimate_cost(provider, model, max(0, prompt_tokens), max(0, completion_tokens)))
    )

    entry = ComputeTokenLedger(
        action="inference_proxy",
        amount=total_tokens,
        provider=provider,
        model=model,
        org_id=org_id or "platform",
        caller=caller or "unknown",
        cost_usd=cost_usd,
    )
    db.add(entry)
    await db.flush()
    logger.debug(
        "inference usage recorded org=%s caller=%s model=%s tokens=%d cost_usd=%s",
        org_id,
        caller,
        model,
        total_tokens,
        cost_usd,
    )
    return entry
