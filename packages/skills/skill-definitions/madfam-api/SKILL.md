---
name: madfam-api
description: MADFAM ecosystem API integration covering Janua authentication (JWT), Dhanam billing (compute tokens), and Enclii deployment.
allowed_tools:
  - api_call
  - file_read
metadata:
  category: integration
  complexity: high
---

# MADFAM API Skill

You work within the MADFAM ecosystem. These three sibling services are critical infrastructure.

## Janua (Authentication)

Janua handles all authentication. Never implement custom auth.

- **Tokens**: JWTs with claims `sub`, `email`, `roles`, `org_id`.
- **FastAPI**: Use the `get_current_user` dependency for route protection.
- **Next.js**: Use the middleware for session validation.
- **Ports**: 4100-4104.

See `references/janua.md` for the full API surface.

## Dhanam (Billing)

Dhanam handles billing and subscriptions.

- **Compute tokens**: Budget enforcement by the orchestrator package.
- **Ledger**: Tracked in the `compute_token_ledger` table.
- **Router**: `apps/nexus-api/src/routers/billing.py`.
- **Ports**: Dhanam service ports.

See `references/dhanam.md` for the full API surface.

## Enclii (Deployment)

Enclii handles deployment of all MADFAM services.

- **Config**: `.enclii.yml` defines all three services.
- **CI/CD**: `deploy-enclii.yml` GitHub Actions workflow.
- **Process**: Build images -> notify Enclii -> rolling deploy.
- **Ports**: 4200-4204.

See `references/enclii.md` for the full API surface.

## Integration Rules

1. Never duplicate auth logic — always delegate to Janua.
2. Always check compute token budget before expensive operations.
3. Use Enclii deployment pipeline — never deploy manually.
4. Read sibling repo `llms-full.txt` files for full API surfaces.
