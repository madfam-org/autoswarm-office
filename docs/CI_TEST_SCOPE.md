# CI Test Scope

Date: 2026-06-04
Owner: Selva engineering

This document defines which test suites are enforced on every PR and which are
intentional non-PR gates. It closes GA-008 from the commercial GA remediation
contract.

## Enforced on every PR

| Workflow job | Scope | Owner |
|---|---|---|
| `lint-ts` | Turbo TypeScript lint across workspace packages with `lint` scripts | Frontend/platform |
| `typecheck` | Turbo TypeScript typecheck; upstream package builds run first | Frontend/platform |
| `test-ts` | Turbo TypeScript tests across workspace packages with `test` scripts | Frontend/platform |
| `lint-py` | Ruff across the Python workspace | Backend/platform |
| `typecheck-py` | Workspace advisory mypy plus zero-regression ratchets for nexus-api, workers, and packages | Backend/platform |
| `test-py` root unit tests | `tests/unit` with coverage artifact | Backend/platform |
| `test-py` Wave 0 regressions | Inference router, budget gate, pgvector memory, campaign graph, approval agent-name response | Backend/platform |
| `critical-path-coverage` | Auth, RLS, onboarding, dispatch, outbound governance, artifact storage, worker auth/lifecycle | Backend/platform |
| `build` | Turbo production build after TS/Python tests | Release engineering |
| `security` | Trivy filesystem scan for HIGH/CRITICAL issues | Security |

## Non-PR Gates

| Suite | Trigger | Owner | Reason |
|---|---|---|---|
| `tests/e2e` / Playwright | Release candidate, staging promotion, or UI-risk PR | Frontend/platform | Browser suites are slower and need stable app services |
| `tests/load` / k6 | Manual `load-test.yml` and Phase 0 Run 4b evidence | Operations | Load tests are capacity exercises, not per-PR correctness checks |
| Production smoke scripts | Staging/prod promotion workflows | Operations | They are environment-targeted and side-effectful |
| Full Python workspace `uv run pytest apps packages tests` | Scheduled hardening run or high-risk refactor | Backend/platform | Some package suites require external services, pgvector, or long-running fixtures |
| Community skill lint deep checks | Pull requests touching `packages/skills/community-skills/` | Skills owner | Advisory by design until community skill fixtures are normalized |

## Change Rule

Any new tenant-safety, money-path, outbound-action, or dispatch-contract
regression test must be included in either the always-on CI scope above or this
document's non-PR gate table with an owner and trigger.
