# Remediation Execution Plan (2026-06-04)

## Scope and objective

This document tracks the next full-remediation cycle from an ROI-first, security-first perspective:

1. eliminate high-impact security gaps,
2. close production-readiness blockers,
3. close remaining operational/compliance debt with verified evidence,
4. keep momentum by implementing only actions that increase reliability or reduce blast radius.

## 2026-06-04 GA-readiness baseline

| Scope | Current score | Top remaining blocker |
|---|---|---|
| MADFAM tenant slice (`admin@madfam.io`) in prod | ~85–90% | Observability and revenue attribution evidence |
| Selva production-truthful baseline | ~88–92% | Load calibration and DR verification |
| Full commercial GA | ~58–65% | Cross-service audit + A2A compliance follow-through |

Execution order remains (highest ROI first):

1. commercial-GA correctness hardening for cross-service tenant and dispatch contracts,
2. security hardening follow-through for URL/adapter risk,
3. OTel + Sentry productionization,
4. Dhanam price-tier + webhook closure + attribution proof,
5. k6 Run 4b + DR drill evidence,
6. phased governance RFC execution (CDC, A2A, residency, failover).

Baseline references:

- [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md)
- [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md)
- [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md)
- [AUDIT_TRAIL_GAP_ANALYSIS.md](./AUDIT_TRAIL_GAP_ANALYSIS.md)
- [apps/nexus-api/nexus_api/routers/gateway.py](../apps/nexus-api/nexus_api/routers/gateway.py)

## Current gap register (priority + ROI)

| Priority | Category | Evidence | Proposed fix | Status |
|---|---|---|---|---|
| 0 | Commercial GA correctness | Gateway auto-dispatch worker-token requests omitted `X-Selva-Tenant-Org`, causing unintended platform fallback risk. | Thread tenant context into gateway events/config and include header on dispatch. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | Gateway rules used `review` and `support`, while `DispatchRequest.graph_type` accepts neither. | Remap to supported graphs or add real graph support with API/worker tests. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | Colyseus department/agent sync fetched Nexus departments with service token but no tenant header. | Include room org context on department list/detail calls and update tests. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | Live campaign email scheduling still had placeholder recipient fallback. | Require selected contact/list or disable live email scheduling until recipient source is real. | ✅ Implemented/tested for current path |
| 0 | Commercial GA correctness | Inference streaming bypassed non-streaming budget/fallback safety posture. | Apply budget preflight and pre-token fallback only; never splice providers mid-stream. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | Approval UI synthesized agent names from IDs. | Return `agent_name` from Nexus approval responses and consume it in Office UI. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | Memory store compatibility count path returned a default zero before async DB load and test embedders failed pgvector dimension checks. | Add async `get_count()`, update callers, and normalize vectors to the storage dimension. | ✅ Implemented/tested |
| 0 | Commercial GA correctness | CI scope did not explicitly cover/document all relevant app/package test trees. | Add Wave 0 regression tests to CI and document non-PR suites with owners. | ✅ Implemented/documented |
| 1 | Security (critical) | ACP Analyst fallback used `requests.get(self.target_url)` on user-provided URL (`acp_analyst.py`) with potential SSRF/DNS-rebind exposure. | Replace fallback with shared safe request builder (`_build_safe_request_kwargs`) and IP-pin request path. | ✅ Implemented |
| 1 | Security (critical) | pricing tools fetched arbitrary URLs without private-IP filtering. | Use shared safe request builder for both catalog URL loading and competitor lookup, and disable env proxy use. | ✅ Implemented |
| 1 | Security (high) | Remaining webhook adapters were validated by tests, but `acp_tasks` still documents DNS rebinding risk across node HTTP calls. | Keep risk in backlog until workflow node URL fetching is fully hardened end-to-end. | 🔄 In progress |
| 2 | Operations enablement | Observability and Sentry runbooks still blocked by real config in production + PP4 env gaps. | Complete PHASE 0 gates and unblock alerting quality gates in CI; office-ui source-map upload and deterministic OTel trace verification are repo-complete. | 🔄 Partial |
| 2 | Revenue correctness | Dhanam price→tier mapping + webhook destination drift remains partially open. | Reconcile production mapping, webhook secrets and URL drift; strict `verify-dhanam-price-tier-map.sh --require-all` evidence path is repo-complete. | 🔄 Partial |
| 2 | Reliability / capacity | k6 Run 4 hard thresholds still below target and staging load scale history still inconsistent. | Repo guardrails shipped: `staging-load` overlay + Run 4b live preflight. Remaining work: named staging run, threshold evidence, and dispatch/QPS calibration. | 🔄 Partial |
| 3 | DR posture | No executed backup/restore drill evidence on record. | Repo guardrails shipped: DB restore drill wrapper + evidence verifier. Remaining work: execute against a named clean staging target and record RTO/RPO metrics. | 🔄 Partial |
| 3 | Compliance posture | Secret rotation calendar was incomplete for Q3 cadence. | Repo schedule/verifier shipped for 2026-07-07; operator must confirm external calendar event and later attach execution evidence. | 🔄 Partial |
| 4 | Platform debt | Prometheus runbook URLs still placeholder in `alerting-rules.yml`. | Replaced placeholders with real internal runbook links (`docs/RUNBOOK.md#alert-response-procedures`). | ✅ Implemented |
| 4 | Engineering debt | `packages/workflows/src/selva_workflows/nodes/python_runner.py` and skill/tool execution surfaces still use `exec/compile` patterns for trusted internal inputs only. | Keep gated but require explicit threat model and review before opening to untrusted input. | 🧭 Watchlist |

## Implementation waves (recommended)

### Wave 0 — Commercial GA correctness (repo-level closed 2026-06-04)

1. Keep the GA-001..GA-008 contracts closed in
   [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md):
   - gateway tenant header propagation,
   - gateway graph-type contract,
   - Colyseus tenant header propagation,
   - streaming inference safety contract,
   - live placeholder cleanup,
   - approval agent-name data path,
   - memory store stub audit,
   - CI test-scope clarity.
2. Treat regressions in these contracts as GA blockers even though they are
   not operator-gated.
3. Do not promote additional live outbound automation if any Wave 0 contract
   regresses.

### Wave 1 — Safety hardening (days 1–3)

1. Finalize external-URL hardening in all tool/agent surfaces:
   - [packages/workflows/src/selva_workflows/acp_analyst.py](../packages/workflows/src/selva_workflows/acp_analyst.py)
   - [packages/tools/src/selva_tools/builtins/pricing_intel.py](../packages/tools/src/selva_tools/builtins/pricing_intel.py)
   - [packages/tools/src/selva_tools/builtins/web.py](../packages/tools/src/selva_tools/builtins/web.py)
   - [packages/tools/src/selva_tools/mcp/client.py](../packages/tools/src/selva_tools/mcp/client.py)
   - [packages/tools/src/selva_tools/builtins/meta_harness.py](../packages/tools/src/selva_tools/builtins/meta_harness.py)
2. Validate hardened paths with targeted regression tests (no suite run):
   - `packages/tools/tests/test_new_tools.py`
   - `packages/tools/tests/test_meta_harness_tools.py`
   - `apps/nexus-api/tests/test_gateway_webhook_remaining_hardened.py`
   - `apps/nexus-api/tests/test_gateway.py`
   - `packages/tools/tests/test_safe_eval.py`
   - `packages/tools/tests/test_safety_hardening.py`
   - `packages/workflows/tests/test_safe_eval.py`
   - `packages/workflows/tests/test_compiler.py`

### Wave 2 — Operational unblock (days 4–7)

1. Execute and archive remaining PHASE_0 gates:
   - OTel + Sentry
   - Dhanam price/tier + webhook
   - 100-worker calibration run after `./scripts/verify-staging-load-run4b-preflight.sh --require-live`
2. Close all runbook placeholders:
   - [infra/prometheus/alerting-rules.yml](../infra/prometheus/alerting-rules.yml) (implemented)
3. Record completion snapshots against:
   - [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md)

### Wave 3 — Risk closure (days 8–14)

1. Run backup/restore DR drill and record RTO/RPO evidence:
   - [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md)
   - `./scripts/run-db-restore-drill.sh --preflight`
   - `./scripts/verify-dr-drill-evidence.sh`
2. Schedule Q3 secret rotation and verify all 90-day operations:
   - [SECRET_ROTATION_POLICY.md](./SECRET_ROTATION_POLICY.md)
   - `./scripts/verify-secret-rotation-schedule.sh`
3. Move audit trail and webhook residual risk tickets only if runtime evidence shows any miss:
   - Track to RFC 0019 and existing webhook follow-on docs.

## Execution checklist (owner + evidence)

- Security owner:
  - Verify safe URL handling in all user-fed endpoints/tools in:
    - [apps/nexus-api/nexus_api/routers/gateway.py](../apps/nexus-api/nexus_api/routers/gateway.py)
    - [packages/tools/src/selva_tools/builtins/pricing_intel.py](../packages/tools/src/selva_tools/builtins/pricing_intel.py)
    - [packages/workflows/src/selva_workflows/acp_analyst.py](../packages/workflows/src/selva_workflows/acp_analyst.py)
- Operations owner:
  - Complete `PHASE_0_REMEDIATION_PLAN` gates 0.1–0.7 with dated evidence.
- Platform owner:
  - Replace placeholder alerting runbook URLs and unblock observability actionability (implemented).

## Hardening debt not yet closed (do not lose this)

- Gateway rebind closure remains a two-stage gap: target URLs are validated at admission and task-start, but workflow-level HTTP clients still perform host-based routing; treat this as a follow-on design item for ACP extraction nodes.
- Any new external URL-capable tool must use:
  - `http_tools._build_safe_request_kwargs`
  - `trust_env=False`
  - DNS pinning + SNI-host preservation

## Short-term stop conditions

- Any PR touching user-driven fetches must include:
  - URL validation or pinned-IP request path,
  - local tests for private-address rejection,
  - log/error detail that identifies secret-unconfigured / malformed input paths.

## Change log

- 2026-06-04: created this plan and patched
  - [packages/workflows/src/selva_workflows/acp_analyst.py](../packages/workflows/src/selva_workflows/acp_analyst.py): safe fallback fetch.
  - [packages/tools/src/selva_tools/builtins/pricing_intel.py](../packages/tools/src/selva_tools/builtins/pricing_intel.py): safe URL fetch for catalog + competitor lookup.
- 2026-06-04 (continued): hardened browser fallback HTTP path and made alerting runbook links actionable.
  - [packages/tools/src/selva_tools/browser.py](../packages/tools/src/selva_tools/browser.py): hardens Playwright fallback `requests` paths with `http_tools._build_safe_request_kwargs`.
  - [infra/prometheus/alerting-rules.yml](../infra/prometheus/alerting-rules.yml): replaced placeholder `runbook_url` values with repository runbook anchors.
- 2026-06-04 (prior): web/security hardening updates in web, MCP stdio, and meta harness files.
  - `packages/tools/tests/test_safe_eval.py`, `packages/tools/tests/test_safety_hardening.py`, `packages/workflows/tests/test_safe_eval.py`, `packages/workflows/tests/test_compiler.py` now cover unsafe expression, command-splitting, MCP stdio, and compiler runtime blocks introduced by the final hardening pass.
- 2026-06-04 (commercial GA update): added Wave 0 for cross-service tenant propagation, gateway dispatch contract, and live placeholder cleanup; linked the platform-wide GA contract.
- 2026-06-04 (commercial GA implementation): implemented/tested GA-001 through GA-007:
  gateway tenant headers, gateway graph contract, Colyseus tenant headers,
  streaming inference safety, campaign email placeholder removal, approval
  `agent_name`, and memory async count/vector compatibility.
- 2026-06-04 (CI scope closure): implemented GA-008 with always-on Wave 0
  Python regressions in `.github/workflows/ci.yml` and explicit non-PR suite
  ownership in [CI_TEST_SCOPE.md](./CI_TEST_SCOPE.md).
- 2026-06-04 (Run 4b guardrail): added `infra/k8s/overlays/staging-load`
  and `scripts/verify-staging-load-run4b-preflight.sh` so load calibration
  requires live `nexus-api` replicas/HPA convergence before k6 runs.
- 2026-06-04 (DR guardrail): added `scripts/run-db-restore-drill.sh`,
  `scripts/verify-dr-drill-evidence.sh`, and `docs/dr-drills/` so Phase 0.5
  restore evidence is generated and verified consistently.
- 2026-06-04 (secret rotation schedule): added
  `docs/secret-rotations/2026Q3-schedule.md` and
  `scripts/verify-secret-rotation-schedule.sh` for Phase 0.7 schedule evidence.
