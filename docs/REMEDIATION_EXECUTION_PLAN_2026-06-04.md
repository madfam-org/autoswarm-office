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

1. security hardening follow-through for URL/adapter risk,
2. OTel + Sentry productionization,
3. Dhanam price-tier + webhook closure + attribution proof,
4. k6 Run 4b + DR drill evidence,
5. phased governance RFC execution (CDC, A2A, residency, failover).

Baseline references:

- [docs/PHASE_0_REMEDIATION_PLAN.md](docs/PHASE_0_REMEDIATION_PLAN.md)
- [docs/OPERATOR_BACKLOG.md](docs/OPERATOR_BACKLOG.md)
- [docs/AUDIT_TRAIL_GAP_ANALYSIS.md](docs/AUDIT_TRAIL_GAP_ANALYSIS.md)
- [apps/nexus-api/nexus_api/routers/gateway.py](apps/nexus-api/nexus_api/routers/gateway.py)

## Current gap register (priority + ROI)

| Priority | Category | Evidence | Proposed fix | Status |
|---|---|---|---|---|
| 1 | Security (critical) | ACP Analyst fallback used `requests.get(self.target_url)` on user-provided URL (`acp_analyst.py`) with potential SSRF/DNS-rebind exposure. | Replace fallback with shared safe request builder (`_build_safe_request_kwargs`) and IP-pin request path. | ✅ Implemented |
| 1 | Security (critical) | pricing tools fetched arbitrary URLs without private-IP filtering. | Use shared safe request builder for both catalog URL loading and competitor lookup, and disable env proxy use. | ✅ Implemented |
| 1 | Security (high) | Remaining webhook adapters were validated by tests, but `acp_tasks` still documents DNS rebinding risk across node HTTP calls. | Keep risk in backlog until workflow node URL fetching is fully hardened end-to-end. | 🔄 In progress |
| 2 | Operations enablement | Observability and Sentry runbooks still blocked by real config in production + PP4 env gaps. | Complete PHASE 0 gates and unblock alerting quality gates in CI. | ⏸ In backlog |
| 2 | Revenue correctness | Dhanam price→tier mapping + webhook destination drift remains partially open. | Reconcile production mapping, webhook secrets and URL drift. | ⏸ In backlog |
| 2 | Reliability / capacity | k6 Run 4 hard thresholds still below target and staging load scale history still inconsistent. | Complete run with stable `nexus-api` replica count and calibrate dispatch/QPS budgets. | ⏸ In backlog |
| 3 | DR posture | No executed backup/restore drill evidence on record. | Run and document restore exercise, RTO/RPO metrics. | ⏸ In backlog |
| 3 | Compliance posture | Secret rotation calendar incomplete for Q3 cadence. | Schedule and execute rotation playbook. | ⏸ In backlog |
| 4 | Platform debt | Prometheus runbook URLs still placeholder in `alerting-rules.yml`. | Replaced placeholders with real internal runbook links (`docs/RUNBOOK.md#alert-response-procedures`). | ✅ Implemented |
| 4 | Engineering debt | `packages/workflows/src/selva_workflows/nodes/python_runner.py` and skill/tool execution surfaces still use `exec/compile` patterns for trusted internal inputs only. | Keep gated but require explicit threat model and review before opening to untrusted input. | 🧭 Watchlist |

## Implementation waves (recommended)

### Wave 1 — Safety hardening (days 1–3)

1. Finalize external-URL hardening in all tool/agent surfaces:
   - [packages/workflows/src/selva_workflows/acp_analyst.py](packages/workflows/src/selva_workflows/acp_analyst.py)
   - [packages/tools/src/selva_tools/builtins/pricing_intel.py](packages/tools/src/selva_tools/builtins/pricing_intel.py)
   - [packages/tools/src/selva_tools/builtins/web.py](packages/tools/src/selva_tools/builtins/web.py)
   - [packages/tools/src/selva_tools/mcp/client.py](packages/tools/src/selva_tools/mcp/client.py)
   - [packages/tools/src/selva_tools/builtins/meta_harness.py](packages/tools/src/selva_tools/builtins/meta_harness.py)
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
   - 100-worker calibration run
2. Close all runbook placeholders:
   - [infra/prometheus/alerting-rules.yml](infra/prometheus/alerting-rules.yml) (implemented)
3. Record completion snapshots against:
   - [docs/PHASE_0_REMEDIATION_PLAN.md](docs/PHASE_0_REMEDIATION_PLAN.md)

### Wave 3 — Risk closure (days 8–14)

1. Run backup/restore DR drill and record RTO/RPO evidence:
   - [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md)
2. Schedule Q3 secret rotation and verify all 90-day operations:
   - [docs/SECRET_ROTATION_POLICY.md](docs/SECRET_ROTATION_POLICY.md)
3. Move audit trail and webhook residual risk tickets only if runtime evidence shows any miss:
   - Track to RFC 0019 and existing webhook follow-on docs.

## Execution checklist (owner + evidence)

- Security owner:
  - Verify safe URL handling in all user-fed endpoints/tools in:
    - [apps/nexus-api/nexus_api/routers/gateway.py](apps/nexus-api/nexus_api/routers/gateway.py)
    - [packages/tools/src/selva_tools/builtins/pricing_intel.py](packages/tools/src/selva_tools/builtins/pricing_intel.py)
    - [packages/workflows/src/selva_workflows/acp_analyst.py](packages/workflows/src/selva_workflows/acp_analyst.py)
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
  - [packages/workflows/src/selva_workflows/acp_analyst.py](packages/workflows/src/selva_workflows/acp_analyst.py): safe fallback fetch.
  - [packages/tools/src/selva_tools/builtins/pricing_intel.py](packages/tools/src/selva_tools/builtins/pricing_intel.py): safe URL fetch for catalog + competitor lookup.
- 2026-06-04 (continued): hardened browser fallback HTTP path and made alerting runbook links actionable.
  - [packages/tools/src/selva_tools/browser.py](packages/tools/src/selva_tools/browser.py): hardens Playwright fallback `requests` paths with `http_tools._build_safe_request_kwargs`.
  - [infra/prometheus/alerting-rules.yml](infra/prometheus/alerting-rules.yml): replaced placeholder `runbook_url` values with repository runbook anchors.
- 2026-06-04 (prior): web/security hardening updates in web, MCP stdio, and meta harness files.
  - `packages/tools/tests/test_safe_eval.py`, `packages/tools/tests/test_safety_hardening.py`, `packages/workflows/tests/test_safe_eval.py`, `packages/workflows/tests/test_compiler.py` now cover unsafe expression, command-splitting, MCP stdio, and compiler runtime blocks introduced by the final hardening pass.
