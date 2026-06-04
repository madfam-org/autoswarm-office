# Commercial GA Remediation Plan

Date: 2026-06-04
Status: active implementation contract
Owner: Selva engineering + MADFAM platform operator
Scope: selva-office path to full commercial GA for MADFAM and downstream tenants

## Purpose

This document turns the Selva codebase readback into an execution contract for
100% commercial GA. It does not replace the Phase 0 sprint plan or the
Autonomous Operations Program. It sits above them as the GA gate map:

- [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) remains the
  sprint plan for operational remediation.
- [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md)
  remains the north-star program plan.
- [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) remains the human-gated action
  list.
- Campaign-specific GA proof remains in
  [COMMERCIAL_GA_CAMPAIGN_ORCHESTRATION_GATES_2026-06-01.md](./COMMERCIAL_GA_CAMPAIGN_ORCHESTRATION_GATES_2026-06-01.md),
  [TULANA_COMMERCIAL_GA_GAP_QUEUE_CONSUMPTION_2026-06-01.md](./TULANA_COMMERCIAL_GA_GAP_QUEUE_CONSUMPTION_2026-06-01.md),
  and [TULANA_COMMERCIAL_GA_EVIDENCE_PRODUCER_2026-06-01.md](./TULANA_COMMERCIAL_GA_EVIDENCE_PRODUCER_2026-06-01.md).

## Definition of 100% commercial GA

Selva is 100% commercial GA when a new qualified tenant can be onboarded,
operate paid work, receive invoices and support, and safely graduate routine
automation lanes without private operator intervention or undocumented
break-glass steps.

The GA bar is evidence-based, not feature-count based.

| Area | GA bar |
|------|--------|
| Tenant safety | All service-token and worker calls carry an explicit tenant target; no shared synthetic tenant is used for paying callers |
| Money path | CRM lead to checkout to subscription tier to invoice/CFDI is traceable and replay-tested |
| Reliability | Tier 1 SLOs have live telemetry, alert routing, load-test evidence, and tested recovery |
| Governance | Consent, voice mode, HITL, idempotency, audit, and data residency answers are available per tenant |
| Product | Core office, approvals, campaigns, billing status, onboarding, and support surfaces have no demo placeholders on live paths |
| Operations | Enclii-first deploy, rollback, observability, secret rotation, backup, and incident runbooks are executable without raw prod access |
| GTM | At least one repeatable paid lane has traction, unit economics, and support process evidence |

Current readback:

| Scope | Estimate | Notes |
|-------|----------|-------|
| MADFAM tenant slice in prod | ~85-90% | Usable for internal deterministic workflows under current safeguards |
| Selva production-truthful baseline | ~88-92% | Security and tenancy foundations mostly implemented |
| Full commercial GA | ~58-65% | Blocked by evidence, cross-service correctness, revenue proof, load, DR, and GTM gates |

## Non-negotiable no-go gates

These gates must be green before Selva is represented as commercial GA for
general tenants.

| Gate | Requirement | Current status | Evidence |
|------|-------------|----------------|----------|
| CGA-0 | No production side effects without explicit target environment and operator intent | Policy exists | AGENTS.md doctrine + runbook discipline |
| CGA-1 | Cross-service tenant propagation is complete | Implemented in repo; rollout evidence pending | Gateway and Colyseus service-token gaps fixed and tested |
| CGA-2 | Dispatch contracts are internally consistent | Implemented in repo; rollout evidence pending | Gateway auto-dispatch rules use only API-accepted `graph_type` values |
| CGA-3 | Observability is actionable | Open | OTel trace + Sentry capture across all critical services |
| CGA-4 | Billing and attribution are proven | Partial | Dhanam price-tier map, webhook replay, paid conversion evidence |
| CGA-5 | Load and recovery are measured | Partial | k6 Run 4b threshold pass + backup/restore RTO/RPO drill |
| CGA-6 | Outbound governance is fail-closed | Mostly implemented | Voice mode, consent ledger, SPF checks, HITL approval evidence |
| CGA-7 | Product live paths are placeholder-free | Improved; broader audit pending | Campaign email placeholder removed/blocked; approval agent names now server-derived |
| CGA-8 | Cross-service audit and compliance path is answerable | Partial | RFC 0019/0020/0021 execution plan and tenant evidence query |
| CGA-9 | Autonomy graduation is policy-driven | Partial | 30-day clean-run criteria per lane before ASK -> ALLOW |

## Immediate remediation wave

Wave 0 is the new highest-priority engineering lane surfaced by the 2026-06-04
codebase ingestion. It should happen before broad commercial GA work because it
removes correctness gaps in cross-service behavior.

| ID | Item | Owner | Acceptance | Status |
|----|------|-------|------------|--------|
| GA-001 | Gateway auto-dispatch must include `X-Selva-Tenant-Org` for worker-token calls | Engineering | Tests prove dispatch requests include the tenant header and no call falls back to `platform` unintentionally | ✅ Implemented/tested |
| GA-002 | Gateway auto-dispatch rules must use API-accepted graph types | Engineering | `review` and `support` are remapped or added with real workers/tests; API rejects no configured gateway rule | ✅ Implemented/tested |
| GA-003 | Colyseus department/agent sync must include tenant header | Engineering | Department list/detail fetches carry room org context; tests updated | ✅ Implemented/tested |
| GA-004 | Inference streaming must match non-streaming safety posture | Engineering | Streaming has budget gate/fallback or a documented, tested no-fallback contract | ✅ Implemented/tested |
| GA-005 | Live campaign scheduling must not use placeholder recipients | Engineering + Product | Email scheduling requires selected contact/list or is disabled for live tenants | ✅ Implemented/tested for current placeholder path |
| GA-006 | Approval UI should stop synthesizing agent names from IDs | Engineering | Server returns `agent_name` or UI resolves agent map reliably | ✅ Implemented/tested |
| GA-007 | Memory store compatibility stubs must be audited | Engineering | `count` has async implementation or callers stop depending on it | ✅ Implemented/tested |
| GA-008 | CI scope must be explicit for all test trees | Engineering | Main CI either runs all intended app/package tests or documents excluded suites with owners | ✅ Implemented/documented |

## Implementation waves

### Wave 0 - correctness hardening (repo-level closed 2026-06-04)

GA-001 through GA-008 are repo-level closed. Keep their tests in CI and do not
expand live automation without preserving these contracts.

### Wave 1 - operational proof (week 1-2)

Execute Phase 0 gates:

1. Provision OTel exporter secrets and verify an end-to-end dispatch trace.
2. Provision Sentry DSNs and source maps; capture synthetic staging errors.
3. Run k6 Run 4b after the `staging-load` overlay and live preflight prove
   `nexus-api` replicas/HPA are pinned at 2.
4. Execute the guarded backup/restore drill wrapper and record RTO/RPO.
5. Record Enclii adapter gaps for any remaining raw break-glass actions.

Primary docs:

- [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md)
- [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md)
- [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md)
- [SLOS.md](./SLOS.md)

### Wave 2 - money-path proof (week 2-4)

Prove the commercial path before calling any campaign lane GA:

1. Complete Dhanam production and staging price-tier mapping.
2. Verify Selva webhook HMAC, replay behavior, tier cache update, and dispatch
   budget change.
3. Run one attributed paid conversion:
   CRM `lead_id` -> Dhanam/Stripe `customer_id` -> Selva tenant tier ->
   invoice/CFDI artifact.
4. Feed required evidence back to Tulana and Converge only through controlled
   evidence producers.

Primary docs:

- [INTEGRATION.md](./INTEGRATION.md)
- [TULANA_COMMERCIAL_GA_EVIDENCE_PRODUCER_2026-06-01.md](./TULANA_COMMERCIAL_GA_EVIDENCE_PRODUCER_2026-06-01.md)
- [COMMERCIAL_GA_CAMPAIGN_ORCHESTRATION_GATES_2026-06-01.md](./COMMERCIAL_GA_CAMPAIGN_ORCHESTRATION_GATES_2026-06-01.md)

### Wave 3 - compliance and audit closure (month 2)

Make tenant and regulator answers queryable:

1. Execute RFC 0019 Phase A for cross-service CDC audit or document the accepted
   interim evidence query path.
2. Implement RFC 0018 Phase D for A2A per-caller tenants before any paying A2A
   caller is onboarded.
3. Start RFC 0020 data residency implementation for SAT-bound Mexican tenants.
4. Keep RFC 0021 multi-region failover behind RFC 0020 topology.

### Wave 4 - product GA polish (month 2-3)

Remove internal/demo assumptions from live tenant paths:

1. Complete onboarding, outbound identity, billing status, campaign scheduling,
   approvals, support, and admin surfaces for non-MADFAM tenants.
2. Add live-mode guards where a feature is still internal-only.
3. Verify accessibility and mobile usability for core approval/dispatch flows.
4. Validate terms, privacy, unsubscribe, and support entrypoints.

### Wave 5 - autonomy graduation and commercial cutover (month 3+)

Graduate lanes only with evidence:

1. Maintain all live outbound lanes in ASK by default.
2. Promote a lane to ALLOW only after 30 days clean run, zero consent incidents,
   no unresolved SLO burns, and operator approval.
3. Keep LinkedIn draft-only.
4. Keep deploy, secret, billing, and data-destructive actions ASK or stronger.

## GA acceptance checklist

Commercial GA requires every row to be complete with dated evidence.

| Check | Evidence location |
|-------|-------------------|
| Cross-service tenant header tests pass | PR/tests for gateway, Colyseus, workers |
| Gateway graph-type contract test passes | Gateway and `swarms.dispatch` tests |
| CI test scope is explicit | [CI_TEST_SCOPE.md](./CI_TEST_SCOPE.md) + `.github/workflows/ci.yml` |
| OTel trace captured for dispatch -> worker -> event | `./scripts/verify-observability-trace.sh --require-trace` output with generated `TRACE_ID` found in Tempo |
| Sentry synthetic errors captured per service | Observability run evidence |
| k6 Run 4b thresholds pass | `./scripts/verify-staging-load-run4b-preflight.sh --require-live` output + [LOAD_TEST_2026-Q2.md](./LOAD_TEST_2026-Q2.md) |
| Backup/restore drill measured | `./scripts/verify-dr-drill-evidence.sh` output + [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) |
| Secret rotation schedule verified | `./scripts/verify-secret-rotation-schedule.sh` output + [SECRET_ROTATION_POLICY.md](./SECRET_ROTATION_POLICY.md) |
| Dhanam price-tier verify OK | `./scripts/verify-dhanam-price-tier-map.sh --staging --require-all` output plus prod equivalent |
| Paid conversion traced end-to-end | Phase 1 revenue proof record |
| Campaign proof pack and outbound gates pass | Campaign GA docs |
| Consent/voice ledger verified | Health endpoint and audit evidence |
| A2A paying-caller path uses per-caller tenant | RFC 0018 execution evidence |
| CDC/residency plan accepted for target buyer class | RFC 0019/0020 evidence |
| Support and incident process tested | RUNBOOK/SLO review evidence |

## Stop conditions

Pause GA promotion if any of these are true:

- A service-token call can mutate or read tenant data without an explicit tenant
  target.
- A live outbound action can send to a placeholder or unverified recipient.
- Billing tier enforcement depends on stale or manual Stripe mapping.
- A Tier 1 path lacks tracing, error capture, or an owner for alerts.
- k6 hard thresholds fail and no tuned production limit is recorded.
- Backup restore cannot be completed within the documented RTO/RPO targets.

## Changelog

| Date | Change |
|------|--------|
| 2026-06-04 | Initial platform-wide commercial GA remediation contract created from codebase ingestion. |
| 2026-06-04 | Implemented and tested GA-001 through GA-007 in repo; operational evidence gates remain open. |
| 2026-06-04 | Implemented GA-008 with Wave 0 CI regressions and explicit non-PR suite ownership in [CI_TEST_SCOPE.md](./CI_TEST_SCOPE.md). |
| 2026-06-04 | Added Run 4b `staging-load` overlay/preflight as required evidence before k6 threshold results are accepted. |
| 2026-06-04 | Added guarded DB restore drill wrapper and strict evidence verifier for the backup/restore GA gate. |
| 2026-06-04 | Added Q3 secret rotation schedule verifier to the GA acceptance checklist. |
