# Commercial GA campaign orchestration gates

Date: 2026-06-01
Status: required Selva orchestration gate for revenue campaigns.

## Purpose

Selva agents can help plan, draft, and maintain SKU campaigns, but they must not invent GA readiness or product claims. This document adds a hard money-path gate to the Tulana SKU campaign orchestration contract.

## Role boundary

| System | Owns | Must not do |
| --- | --- | --- |
| Tulana | SKU readiness, proof points, pricing evidence, blocker/waiver state. | Send campaigns or invent buyer consent. |
| Selva | Agent planning, copy drafting from evidence, task orchestration, HITL routing. | Override readiness, claim GA, or send without PhyndCRM consent gate. |
| PhyndCRM | Contacts, consent, campaign review/send, engagement attribution. | Mark an SKU Commercial GA without Dhanam/Tulana/Converge evidence. |
| Dhanam | Catalog, checkout, payment, ledger, entitlement, payout evidence export. | Treat checkout as recognized revenue before payment/payout evidence. |
| Converge Dash | Governed revenue metric import and stakeholder evidence. | Accept optimistic/manual revenue numbers without source evidence. |

## Agent acceptance criteria

Selva must reject or downgrade campaign work when:

- `commercial_ga_status` is absent.
- A SKU is `blocked` or `paused`.
- A paid-GA task is requested for a `candidate`.
- Proof points are missing or unverified.
- G0-G9 money-path evidence is incomplete for `ga_ready`.
- `do_not_claim` guardrails conflict with requested copy.
- PhyndCRM contact consent/suppression state is unavailable.
- Human approval has not been recorded for outbound actions.

## Required agent workflow

1. Import Tulana/Dhanam commercial proof pack.
2. Classify every SKU as `blocked`, `candidate`, `ga_ready`, or `paused`.
3. For `candidate`, create only discovery, waitlist, or warm-pilot tasks.
4. For `ga_ready`, create paid campaign planning tasks.
5. Draft copy using proof points only.
6. Attach `do_not_claim` guardrails to every task.
7. Send drafts to human review.
8. Hand approved payloads to PhyndCRM with idempotency keys.
9. Monitor PhyndCRM engagement outcomes.
10. Feed buyer-signal summaries back to Tulana.
11. Feed payment/conversion evidence to Dhanam/Converge only through controlled exports.

## Initial campaign lane decisions

| SKU | Selva lane | Current permitted action |
| --- | --- | --- |
| `karafiel__contador` | `first_pesos_primary` | Prepare proof-backed copy and warm-pilot tasks; paid broad send waits for G0-G9. |
| `coforma__startup` | `first_pesos_backup` | Prepare CAB/PMF buyer discovery copy; paid broad send waits for G0-G9. |
| `tezca__pro` | `inbound_validation` | Waitlist/inbound only until proof pack is stronger. |
| `dhanam__pro` | `billing_smoke` | Internal checkout smoke only unless explicitly chosen for low-ticket proof. |
| `pravara-mes__starter` | `account_based_enterprise` | Discovery and account qualification only. |

## Required Selva tests

- Import rejects missing `commercial_ga_status`.
- Paid campaign task rejects `candidate`.
- Draft-copy tool excludes every `do_not_claim` item.
- HITL approval is required before PhyndCRM handoff.
- PhyndCRM handoff includes idempotency key and gate evidence references.
- Buyer-signal feedback contains no raw contact PII.
- Campaign result review can mark `converted` only when Dhanam payment evidence exists.
- Revenue summary can mark `revenue_evidenced` only when Converge import succeeds.

## Related docs

- Existing Selva campaign orchestration: `TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md`
- PhyndCRM campaign gates: `../../phynd-crm/docs/COMMERCIAL_GA_CAMPAIGN_SKU_GATES_2026-06-01.md`
- Dhanam first-pesos runbook: `../../dhanam/docs/FIRST_PESOS_COMMERCIAL_GA_MONETIZATION_2026-06-01.md`
