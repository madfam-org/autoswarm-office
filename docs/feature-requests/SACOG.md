# Selva Agentic Commerce Orchestration Gateway (SACOG)

> **Status**: proposed; canonical spec at `internal-devops/rfcs/0018-selva-acog-agentic-commerce-orchestration.md`

This document is a stub forward-pointer so future implementation sessions in
this repo encounter the SACOG specification when they grep for "agentic
commerce" or "orchestration gateway" within `selva-office/`.

The full RFC lives in the ecosystem-wide policy repo (`internal-devops/rfcs/0018-...`)
because the feature spans `selva-office`, `dhanam`, `janua`, `phynd-crm`, `karafiel`,
and `tezca`.

## TL;DR

Build a stateful MCP-translation gateway in `apps/sacog-gateway/` that turns Selva
into the protocol-agnostic merchant-side bridge for Stripe ACP / Google UCP /
Coinbase x402 / B2B agent-payment protocols. Capture margin via a 3-tier hybrid
pricing model:

1. **Tier 1** — base monthly "legibility" fee (predictable revenue floor)
2. **Tier 2** — per-action compute pricing (margin protection at scale)
3. **Tier 3** — outcome-based success fee (1-3% of routed transactions; the engine)

## Sequencing snapshot

| Phase | Scope | Effort |
|---|---|---|
| 1 | Spec + protocol-conformance fixtures | ~2w |
| 2 | Gateway core + Forgesight reference integration | ~4w |
| 3 | Attribution dashboards (PhyndCRM-side) | ~3w |
| 4 | Stripe ACP integration (first paying merchant) | ~3w |
| 5 | Tier 2 metering + UCP / x402 / B2B | ~4w |
| 6 | Self-serve dashboards + GA | ~2w |

Total: ~18 weeks single-team.

## Implementation kickoff checklist

When the implementation session begins, run through the checklist in
`internal-devops/rfcs/0018-selva-acog-agentic-commerce-orchestration.md` § 8.

## Cross-refs

- Atrium overlay UI: PR `selva-office#161`
- Wave 5 SSO + entitlements (mandate-signing primitive): `janua#376`, `selva-office#164`
- Per-action metering pattern reference: dragon-egg Phase 2 in `selva-office#160`
