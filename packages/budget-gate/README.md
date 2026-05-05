# madfam-budget-gate

Redis-backed token + USD spend gate for autonomous LLM campaigns.

This package is the bedrock safety mechanism that prevents the swarm
from silently draining LLM credits.  It tracks token spend and USD
spend per scope (org / agent / global), enforces daily and monthly
caps, and returns ALLOW / DENY / SOFT-WARN before each LLM call.

## Why

Autonomous campaigns dispatch many LLM calls per minute.  A single
mis-configured playbook can burn through a month of credits in an
hour.  Credit-side rate limiting at provider level is too coarse
(per-API-key, no concept of per-agent or per-campaign budgets) and
too late (you find out after spend is committed).

`madfam-budget-gate` enforces budgets *at dispatch time*, in
milliseconds, using Redis counters.

## Quick start

```python
from madfam_budget_gate import BudgetGate, BudgetScope, BudgetExhausted

gate = BudgetGate.from_env()

# Pre-call gate
decision = await gate.check(
    scope=BudgetScope(org_id="acme", agent_id="reddit_promo_v1"),
    estimated_tokens=2000,
    estimated_cost_usd=0.04,
)
if not decision.allowed:
    raise BudgetExhausted(decision.reason, decision.retry_after_seconds)

# ... call LLM ...

# Post-call recording — pass the real usage from the provider response
await gate.record(
    scope=BudgetScope(org_id="acme", agent_id="reddit_promo_v1"),
    actual_tokens=1957,
    actual_cost_usd=0.038,
    provider="anthropic",
    model="claude-sonnet-4-6",
)
```

## Scopes

A `BudgetScope` is the unit of cap enforcement.  Three levels:

  - `BudgetScope()` — global / catch-all.
  - `BudgetScope(org_id="acme")` — org-level.
  - `BudgetScope(org_id="acme", agent_id="reddit_promo_v1")` — agent-level.

Every check enforces the caps of the supplied scope **and** every
parent scope.  The most restrictive cap wins.  Spend recorded against
an agent scope automatically counts against the org and global caps too.

## Cap resolution order

1. Per-scope override stored in Redis (set via `gate.set_cap(...)`).
2. Org-level override (one level up the chain).
3. Global override.
4. Env-defined default (`BUDGET_GATE_DEFAULT_DAILY_USD`, etc.).

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `BUDGET_GATE_REDIS_URL` | falls back to `REDIS_URL` then `redis://localhost:6379` | Redis URL |
| `BUDGET_GATE_DEFAULT_DAILY_USD` | `50.0` | Global daily USD cap |
| `BUDGET_GATE_DEFAULT_MONTHLY_USD` | `1000.0` | Global monthly USD cap |
| `BUDGET_GATE_DEFAULT_DAILY_TOKENS` | `5000000` | Global daily token cap |
| `BUDGET_GATE_DEFAULT_MONTHLY_TOKENS` | `100000000` | Global monthly token cap |
| `BUDGET_GATE_SOFT_WARN_THRESHOLD` | `0.8` | Fraction of cap that triggers soft-warn |
| `BUDGET_GATE_FAIL_OPEN` | unset (= fail-closed) | If truthy, allow calls when Redis is unreachable |
| `BUDGET_GATE_ENABLED` | unset (= disabled) | Worker/router toggle for the inference integration |

## Failure modes

If Redis is unreachable, the gate **fails CLOSED** (denies every
call) by default.  Silently leaking spend during a Redis outage is a
worse business risk than a brief LLM-call outage.

To invert this for ops contexts where uptime trumps cost-risk, set
`BUDGET_GATE_FAIL_OPEN=true`.  This is intentionally not the default.

## Cost model

Hardcoded in [`cost_model.py`](src/madfam_budget_gate/cost_model.py).
Covers Anthropic (Opus / Sonnet / Haiku 4.x), OpenAI (GPT-4o family,
o1), DeepInfra, Together, Fireworks, Groq, Mistral.

Unknown `(provider, model)` pairs **fall back to the Claude Opus
rate** rather than 0 — the gate must err on the side of
overestimating spend, never under.

## FastAPI introspection

```python
from fastapi import FastAPI
from madfam_budget_gate import BudgetGate, build_router

app = FastAPI()
gate = BudgetGate.from_env()
app.include_router(build_router(gate))
```

Exposes:

  - `GET /budget-gate/health`
  - `GET /budget-gate/status?org_id=&agent_id=&tag=`
  - `GET /budget-gate/cap?org_id=&agent_id=&tag=`

Read-only on purpose — cap mutation belongs in audited ops tooling.

## Testing

```bash
uv run pytest packages/budget-gate/
```

Tests use `fakeredis.aioredis` so no real Redis needed.

## Out of scope

- Web UI / dashboard
- PostHog event emission (separate PR)
- Multi-region distribution
- Stripe-style billing reconciliation
