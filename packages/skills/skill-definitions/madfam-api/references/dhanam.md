# Dhanam Billing API

## Overview
Dhanam manages billing, subscriptions, and compute token budgets for the MADFAM ecosystem.

## Compute Tokens
- Each operation has a token cost (see `ComputeTokenManager.COST_TABLE`).
- Budget is checked before dispatch and deducted on execution.
- The `compute_token_ledger` table is the durable record of all debits/credits.

## Key Endpoints
- `GET /billing/balance` — Current compute token balance
- `GET /billing/usage` — Usage history with time range filter
- `POST /billing/topup` — Add compute tokens (admin only)
- `GET /billing/plans` — Available subscription plans

## Integration
```python
from nexus_api.routers.billing import router as billing_router
# Budget enforcement is handled by the orchestrator package
```

## Cost Table
| Action | Cost |
|--------|------|
| draft_agent | 50 |
| dispatch_task | 10 |
| llm_call | 1-5 |
