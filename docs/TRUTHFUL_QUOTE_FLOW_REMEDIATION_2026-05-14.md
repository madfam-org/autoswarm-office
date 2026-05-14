# Selva truthful quote orchestration roadmap

Last updated: 2026-05-14

## Scope

Selva agents must be able to generate Tablaco quotes through Yantra4D/Cotiza without human superadmin credentials and without presenting fallback pricing as final.

## Current evidence

- `GenerateQuoteTool` supports project-based Yantra quote requests and structured Cotiza quote requests.
- Unit tests prove the tool routes project slugs to Yantra and structured geometry to Cotiza.
- The tool requires `market_verified=true` by default and fails closed when a downstream quote is not market verified.
- 2026-05-14 update adds service-token propagation for Yantra and Cotiza calls.

## Production gap

Selva still needs provisioned Janua/Enclii-backed service credentials with the minimum scopes required for live Tablaco quoting.

## Remediation plan

1. Create a dedicated Selva quote service account.
2. Grant only the required scopes: `yantra4d:quote`, `cotiza:quote`, `forgesight:read`, and later `phynd:engagement.write`.
3. Store service credentials through Enclii secrets, not human accounts.
4. Configure `SELVA_YANTRA4D_SERVICE_TOKEN` and `SELVA_COTIZA_SERVICE_TOKEN`.
5. Keep `require_market_verified=true` as the default.
6. Map downstream failures to agent-actionable messages: auth missing, tier denied, market data unavailable, quote needs review, and client-ready.
7. Add staging/live contract tests once the service account exists.

## Acceptance gates

- Selva can request a Tablaco quote without superadmin credentials.
- Selva refuses to report a final quote unless the downstream response is market verified.
- Service-token headers are covered by unit tests.
- Live contract tests use service credentials only.
