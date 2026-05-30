# RFCs

Design docs for non-trivial changes. Each RFC gets a number, a status,
and lives as a single markdown file in this directory.

## Index

| # | Title | Status | Program phase |
|---|---|---|---|
| [0001](./0001-onboarding-improvements.md) | Onboarding improvements informed by category benchmark | Draft | — |
| [0018](./0018-a2a-external-tenant-model.md) | A2A external tenant model | Accepted | Phase 5 (§ 5.4) |
| [0019](./0019-cross-service-cdc-audit-topic.md) | Cross-service CDC audit topic | Accepted | Phase 4 |
| [0020](./0020-per-tenant-data-residency.md) | Per-tenant data residency | Accepted | Phase 4 |
| [0021](./0021-multi-region-failover.md) | Multi-region failover | Accepted | Phase 4 (after 0020) |
| — | [phygital-quote-truth-contract.md](./phygital-quote-truth-contract.md) | Accepted | Phase 3 |

North-star sequencing: [../AUTONOMOUS_OPERATIONS_PROGRAM.md](../AUTONOMOUS_OPERATIONS_PROGRAM.md).

## When to write one

- Any proposal that touches onboarding, auth, or consent surfaces.
- Any proposal that would change a cross-service contract (Janua,
  Dhanam, Karafiel, Selva's `/v1` inference proxy).
- Any proposal that adopts or rejects a competitor pattern after
  deliberate comparison.

Small bugfixes, single-service refactors, and product tweaks do not
need an RFC — open a PR with a clear description instead.

## Status lifecycle

`Draft` → `In review` → (`Accepted` | `Rejected` | `Superseded`)

Accepted RFCs may still receive amendments; use a new RFC that marks
the original superseded rather than editing history.
