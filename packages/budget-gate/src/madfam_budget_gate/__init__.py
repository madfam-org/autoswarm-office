"""madfam-budget-gate — Redis-backed token + USD spend gate.

Bedrock safety mechanism for autonomous LLM campaigns.  Tracks token
spend and USD spend per scope (org / agent / global), enforces daily
and monthly caps, and returns ALLOW / DENY / SOFT-WARN before each
LLM call.

Quick start
-----------

::

    from madfam_budget_gate import BudgetGate, BudgetScope, BudgetExhausted

    gate = BudgetGate.from_env()
    decision = await gate.check(
        scope=BudgetScope(org_id="acme", agent_id="reddit_promo_v1"),
        estimated_tokens=2000,
        estimated_cost_usd=0.04,
    )
    if not decision.allowed:
        raise BudgetExhausted(decision.reason, decision.retry_after_seconds)

    # ... call LLM ...

    await gate.record(
        scope=BudgetScope(org_id="acme", agent_id="reddit_promo_v1"),
        actual_tokens=1957,
        actual_cost_usd=0.038,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
"""

from .cost_model import estimate_cost, known_providers
from .gate import BudgetExhausted, BudgetGate, GateDecision
from .redis_store import RedisStore
from .scope import BudgetScope, CapConfig, ResolvedCaps

__all__ = [
    "BudgetExhausted",
    "BudgetGate",
    "BudgetScope",
    "CapConfig",
    "GateDecision",
    "RedisStore",
    "ResolvedCaps",
    "estimate_cost",
    "known_providers",
]

__version__ = "0.1.0"


def __getattr__(name: str):
    """Lazy import for the FastAPI router so the optional ``fastapi``
    extra isn't required for the core gate."""
    if name == "build_router":
        from .api import build_router

        return build_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
