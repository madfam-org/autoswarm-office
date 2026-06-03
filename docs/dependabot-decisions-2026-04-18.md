# Dependabot sweep decisions — 2026-04-18

> **Context:** During the Enclii remediation session, dependabot PR #19 (a single
> group bump containing 36 production-dep updates) was the standing backlog on
> selva-office. This doc records per-bump decisions so future dependabot
> runs (and human reviewers) have context.

## Decision

Closed PR #19 in favor of per-package migration PRs raised on dependabot's
next scan.

## Held for dedicated migration PRs

These are breaking upgrades that require code edits, not type-only or
config-compatible bumps. Each needs a dedicated PR with a test pass + any
required code migration. They'll re-raise on dependabot's next scan.

| Dep | From → To | Migration cost |
|---|---|---|
| `next` | 15.1.5 → 16.2.4 | Medium — App Router + RSC edge cases |
| `tailwindcss` | 3.4.17 → 4.2.2 | **High** — config format rewrite (CSS-first) |
| `typescript` | 5.7.3 → 6.0.3 | Medium — new strict checks likely surface existing issues |
| `vitest` | 2.1.8 → 4.1.4 | Medium — config + API shape changes |
| `@vitejs/plugin-react` | 4.3.4 → 6.0.1 | Low–Medium — peer-dep churn |
| `@colyseus/core` | 0.15.57 → 0.17.41 | **High** — breaking schema changes |
| `@colyseus/schema` | 2.0.35 → 4.0.20 | **High** — wire format incompatible |
| `@colyseus/ws-transport` | 0.15.3 → 0.17.13 | Paired with above |
| `jsdom` | 24.x → 29.x | Low — test env only |
| `jose` | 5.2.0 → 6.2.2 | Low — ESM-only, import shape changes |
| `autoprefixer` | 10.4.20 → 10.5.0 | Paired with tailwind migration |
| `postcss` | 8.4.49 → 8.5.10 | Paired with tailwind migration |

## Safe-to-merge (next scan)

These are patch/minor bumps that should merge cleanly when dependabot
re-raises them individually:

| Dep | From → To | Notes |
|---|---|---|
| `posthog-js` | 1.360.2 → 1.369.2 | Patch |
| `pino` | 9.14.0 → current | Patch |
| `redis` | 4.7.0 → 4.7.x | Patch |
| `dotenv` | 16.4.7 → 16.4.x | Patch |
| `express` | 4.21.2 → 4.21.x | Patch |

(Other ~20 minor/patch bumps inside the #19 group also land here when
raised individually.)

## Operator action

None in this PR. When dependabot next scans, expect:
- ~25 small PRs re-opened individually — merge as they arrive
- ~8–10 major PRs re-opened — each claims its own review cycle + migration doc

## Related context

- Enclii saw the same pattern with dhanam + janua dependabot backlogs on
  the same day — sibling sweep docs exist there.
- Tailwind 4 and eslint 10 migrations are shared pain across the
  ecosystem; see `internal-devops/roadmaps/2026-04-session-backlog.md`
  for tracking.

## References

- Closed PR: https://github.com/madfam-org/selva-office/pull/19
- ESLint 10 companion cleanup shipped today: selva-office#42
- Brand-naming convention (Karafiel/Kafi split) verified: internal-devops/docs/brand/architecture.md
