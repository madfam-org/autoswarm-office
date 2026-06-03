# Selva Tool + Skill 100% Coverage Plan

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


> **Status: shipped 2026-04-18.** All six phases landed as PRs #50–#57
> on `main`. Registry now has ~65 tool modules / ~258 tool classes /
> 26 skills. Follow-up admin/tenant audience split shipped as PRs
> #60–#65 (see `CLAUDE.md` ## Tool + Skill Audience Split).
>
> This document is kept as a historical artifact of the plan + phasing
> rationale. For the current tool/skill surface, check
> `packages/tools/src/selva_tools/builtins/` directly.
>
> **Source:** 2026-04-18 capability audit.
> **Goal:** The Selva swarm can (1) stabilize + maintain our infrastructure,
> (2) improve the platform autonomously, and (3) onboard a new tenant end-to-end
> — without requiring a human operator to bridge capability gaps.

Current state at audit: 43 tool modules, ~150 tool classes, 19 skills.
Coverage: ~70% infra / ~25% meta / ~15% tenant onboarding.

Target state: ~65 tool modules, ~230 tool classes, 28 skills.

## Phasing principle

Order = leverage × urgency × dependency-availability.

- **Phase 1 — Infra ops gaps** (close the gaps I hit this session)
- **Phase 2 — Tenant onboarding primitives** (individual service CRUDs)
- **Phase 3 — Tenant onboarding skill** (composite, depends on Phase 2)
- **Phase 4 — Meta-improvement**
- **Phase 5 — Observability + data lifecycle**
- **Phase 6 — Communications + adjacent**

Each phase ships independently. Tests first, then tools, then skill composition.

---

## Phase 1 — Infra ops (close session-observed gaps)

### 1.1 `argocd.py` — ArgoCD app + ApplicationSet management

Tools:
- `argocd_list_apps` — filter by project, status, namespace
- `argocd_get_app` — full status, resources, sync history
- `argocd_sync_app` — trigger sync with revision / prune / force
- `argocd_refresh_app` — soft / hard refresh
- `argocd_register_project` — writes a `config.json` to enclii's ApplicationSet watched path + commits via `github_admin`

All via `argocd` service account token mounted in the selva namespace. Falls through to direct K8s API if server unreachable.

### 1.2 `k8s_diagnostics.py` — read-side Kubernetes

Tools:
- `k8s_get_pods` — filter by namespace / label selector, structured output
- `k8s_describe_pod` — events, containers, volumes, conditions as dict
- `k8s_get_events` — namespace-scoped, sortable by lastTimestamp
- `k8s_get_replicasets` — including DESIRED/CURRENT/READY
- `k8s_get_pvcs` — including bound status + storage class
- `k8s_rollout_status` — deployment/statefulset/daemonset (like `kubectl rollout status`)

Uses the existing in-cluster SA where available; otherwise mounted kubeconfig.

### 1.3 `cloudflare_tunnel.py` — Zero Trust Tunnel CRUD

Tools:
- `cf_tunnel_list`
- `cf_tunnel_create` (returns tunnel id + token)
- `cf_tunnel_list_routes` / `cf_tunnel_add_route` / `cf_tunnel_delete_route`
- `cf_tunnel_list_ingress_rules` / `cf_tunnel_put_ingress`

Blocked on session: could not deploy madlab/sim4d/subtext public URLs because Tunnel routes were a manual operator step.

### 1.4 `cloudflare_r2.py` — R2 bucket + credential CRUD

Tools:
- `r2_bucket_list`
- `r2_bucket_create` (with optional lifecycle rule)
- `r2_bucket_delete`
- `r2_cors_set`
- `r2_credential_create` / `r2_credential_list` / `r2_credential_delete`

Blocked on session: subtext needs `subtext-audio` bucket; sim4d needs `sim4d-simulations`. Tool didn't exist.

### 1.5 `cloudflare_saas.py` — Custom hostnames (for SaaS tenant onboarding)

Tools:
- `cf_saas_hostname_list`
- `cf_saas_hostname_add` (handles SSL validation records)
- `cf_saas_hostname_status`
- `cf_saas_hostname_delete`
- `cf_saas_fallback_origin_set`

### 1.6 `kustomize.py` — digest pin + edit image

Tools:
- `kustomize_list_images`
- `kustomize_set_image` — equivalent of `kustomize edit set image`, commits via `github_admin`
- `kustomize_build` — dry-run to validate

### 1.7 `backup_ops.py` — pgBackRest + generic backup/restore

Tools:
- `pgbackrest_info` (via the postgres sidecar)
- `pgbackrest_backup` (full / diff / incr)
- `pgbackrest_restore` (with target-time)
- `postgres_dump` (schema + data, to R2)
- `postgres_restore` (from R2 object)

### 1.8 Tests + skill updates

- ~40 tests across the new modules
- Update the `operations` skill to reference `argocd_*` + `k8s_*` tools
- New skill: `cluster-triage` (composes K8s diag + ArgoCD + enclii into an incident-runbook-executor)

**Deliverable:** PR with all 8 modules + 1 new skill + updated `operations` skill + tests green.

---

## Phase 2 — Tenant onboarding primitives

### 2.1 `janua_admin.py` — OAuth client + user CRUD

Tools:
- `janua_oauth_client_create` (returns client_id, client_secret, issuer)
- `janua_oauth_client_list`
- `janua_oauth_client_update` (rotate secret, update redirect URIs)
- `janua_oauth_client_delete`
- `janua_user_create_with_roles`
- `janua_tenant_create` — if Janua supports multi-tenant; otherwise org-group
- `janua_org_group_map_claim` — maps IdP group claim to `org_id`

Existing `JanuaOidcRedirectRegisterTool` covers one endpoint; this module is the complete admin surface.

### 2.2 `dhanam_provisioning.py` — tenant + subscription CRUD

Tools:
- `dhanam_tenant_create` (accepts RFC, legal_name, contact_email)
- `dhanam_subscription_create` (plan_id, credit_ceiling, billing_cycle)
- `dhanam_subscription_update`
- `dhanam_credit_ledger_query` (by tenant, period)
- `dhanam_link_stripe_customer` (for outbound billing)

### 2.3 `phyndcrm_provisioning.py`

Tools:
- `phyndcrm_tenant_create` (creates tenant_config row with voice_mode, consent, default_pipeline_id)
- `phyndcrm_user_create`
- `phyndcrm_pipeline_bootstrap` (creates a named pipeline with default stages)
- `phyndcrm_seed_demo_data` (for onboarding demos)

### 2.4 `karafiel_provisioning.py`

Tools:
- `karafiel_org_create` (RFC, razón_social, régimen_fiscal, domicilio_fiscal)
- `karafiel_sat_cert_upload` (.cer / .key / password)
- `karafiel_org_certify` (calls SAT for PAC registration)
- `karafiel_invoice_series_create` (serie + folio)

### 2.5 `resend_domain.py`

Tools:
- `resend_domain_add` (returns DKIM/SPF/DMARC records as list)
- `resend_domain_verify` (polls verification state)
- `resend_domain_list`
- `resend_domain_delete`

Complements existing `resend_webhook_create`.

### 2.6 `stripe_connect.py` — for tenants that bill their own customers

Tools:
- `stripe_connect_account_create`
- `stripe_connect_onboarding_link`
- `stripe_connect_payout_list`

### 2.7 `selva_office_provisioning.py`

Tools:
- `selva_office_seat_create` (org_id, janua_user_sub, default_skills[])
- `selva_office_seat_update_roles`
- `selva_office_tenant_config_get`
- `selva_office_tenant_config_put` (voice_mode, AUTO_DISPATCH_ENABLED, etc.)

### 2.8 `tenant_identity_reconciliation.py`

The cross-cutting headache. Every tenant has identities in Janua / Dhanam / PhyndCRM / Karafiel / Selva Office. This module owns the mapping.

Tools:
- `tenant_resolve` — given any one ID, returns all four
- `tenant_create_identity_record` — a new row in a central `tenant_identities` table with all four IDs
- `tenant_validate_consistency` — flags drift (e.g. Dhanam active but Janua deleted)

Requires a new table + migration in `selva-nexus-api`.

**Deliverable:** 8 modules + migration 0024 + tests. No skill yet — Phase 3 composes.

---

## Phase 3 — tenant-onboarding composite skill

### 3.1 `skill-definitions/tenant-onboarding/SKILL.md`

Orchestrates Phase 2 primitives. Canonical flow:

1. Intake (name, RFC, primary domain, plan)
2. Janua OAuth client (`janua_oauth_client_create`)
3. Janua org group → org_id claim (`janua_org_group_map_claim`)
4. Dhanam tenant + plan (`dhanam_tenant_create` + `dhanam_subscription_create`)
5. PhyndCRM tenant + default pipeline (`phyndcrm_tenant_create` + `phyndcrm_pipeline_bootstrap`)
6. Karafiel org + SAT cert prompt (`karafiel_org_create`; SAT upload is operator)
7. Resend domain add + DKIM/SPF/DMARC surfaced (`resend_domain_add`)
8. R2 bucket provisioning (`r2_bucket_create`, Phase 1)
9. Cloudflare for SaaS hostname (`cf_saas_hostname_add`, Phase 1)
10. Selva Office seat (`selva_office_seat_create`)
11. Tenant identity reconciliation row (`tenant_create_identity_record`)
12. Welcome email + onboarding checklist (via `send_email` + HITL approval)

Step 6 + step 7 have natural HITL gates (legal sig + DNS record publication). Skill metadata declares `reversibility_cost: high`, maxes at `ASK_QUIET`.

### 3.2 `skill-definitions/tenant-offboarding/SKILL.md`

Reverse. Cancel Dhanam subscription, revoke Janua client, archive PhyndCRM data, delete Karafiel org (with SAT de-registration), delete Resend domain, drop R2 bucket (with retention), remove CF hostname, deactivate Selva Office seat, mark reconciliation record `offboarded`. HITL-gated at every irreversible step.

### 3.3 `skill-definitions/tenant-migration/SKILL.md`

Plan tier change (upgrade/downgrade), execute quota updates across Dhanam + Selva Office + PhyndCRM quotas, surface email.

### 3.4 `skill-definitions/quota-management/SKILL.md`

Continuous: credit cap alerts, overage handling, auto-throttle via tenant_config. Plays back through `operations`.

**Deliverable:** 4 skills + integration tests.

---

## Phase 4 — Meta-improvement

### 4.1 `meta_harness.py` — wrap `tezca/experiments/meta-harness/`

Per 2026-04-17 memory. Tools:
- `meta_harness_budget_gate`
- `meta_harness_route` (Selva inference routing)
- `meta_harness_role_summary`
- `meta_harness_convergence_check`
- `meta_harness_submit_round`
- `meta_harness_escalate_tier`

### 4.2 `hitl_introspection.py` — query own trust state

Tools:
- `hitl_get_my_bucket_state` (agent_id, action_category → BucketState)
- `hitl_get_effective_tier` (bucket_key, decision_nonce → ASK/QUIET/SHADOW/ALLOW)
- `hitl_recent_decisions` (last N from `hitl_decisions`)
- `hitl_why_asked` (decision_id → narrative: sample-limited / LCB-below-threshold / locked / forced-sample)

### 4.3 `tool_catalog.py` — introspect own capabilities

Tools:
- `list_my_tools` (filter by category, name pattern)
- `search_tools_by_capability` (free-text → ranked tool candidates)
- `describe_tool` (name → parameters_schema + docstring)

### 4.4 `factory_manifest.py` — wrap shared `madfam-factory-manifest` package

Tools:
- `factory_manifest_publish`
- `factory_manifest_verify`
- `factory_manifest_get_for_repo`

### 4.5 `skill_performance.py` — bandit signal emit

Tools:
- `skill_record_outcome` (skill_id, task_id, outcome, duration_ms) — feeds the ThompsonBandit
- `skill_get_metrics` (skill_id, period → success_rate, avg_duration, p95)

### 4.6 `skill-definitions/platform-evolution/SKILL.md`

Composite skill: read HITL state → consult tool catalog → propose new tool OR skill OR version bump → write PR via `github_admin` + `coding` skill.

**Deliverable:** 5 modules + 1 skill + tests.

---

## Phase 5 — Observability + data lifecycle

### 5.1 `prometheus.py`

- `prom_query` (instant)
- `prom_query_range` (with step)
- `prom_alerts_active` (read Alertmanager)
- `prom_silence_create` (for planned maintenance)

### 5.2 `loki.py`

- `loki_query_range` (LogQL, time window, limit)
- `loki_labels` (enumerate)

### 5.3 `sentry.py`

- `sentry_issue_list` (project, status, query)
- `sentry_issue_get`
- `sentry_issue_update` (resolve, assign, archive)
- `sentry_event_list_for_issue`
- `sentry_breadcrumbs_get` (for Seer-style analysis)

### 5.4 `db_lifecycle.py`

- `db_dump_to_r2` (postgres pg_dump → R2 object)
- `db_restore_from_r2`
- `db_mask_and_copy` (prod → staging with PII masking per table)
- `db_size_report`

### 5.5 `grafana.py` (read-only agent tools)

- `grafana_dashboard_list`
- `grafana_panel_export` (PNG / snapshot URL for embedding in reports)

**Deliverable:** 5 modules + tests. Two new skills: `incident-triage`, `staging-refresh`.

---

## Phase 6 — Communications + adjacent

### 6.1 `twilio_sms.py` — SMS (MX + international)
### 6.2 `discord.py` — webhook + bot message
### 6.3 `telegram.py` — bot message
### 6.4 `voice_call.py` — outbound call via Twilio Voice or ElevenLabs
### 6.5 `belvo_spei.py` — Mexican bank-transfer initiation + status (existing `accounting` tools compute; this executes)
### 6.6 `meeting_scheduler.py` — 3-party free/busy reconciliation (wraps existing `calendar_tools`)

**Deliverable:** 6 modules + tests. 1 new skill: `outbound-voice` (for sales/support agents).

---

## Summary of additions

| Phase | New modules | New tools | New skills | New tests |
|---|---|---|---|---|
| 1 | 7 (+ skill) | ~28 | 1 | ~45 |
| 2 | 8 (+ migration) | ~35 | 0 | ~55 |
| 3 | 0 | 0 | 4 | ~15 |
| 4 | 5 | ~18 | 1 | ~30 |
| 5 | 5 | ~16 | 2 | ~30 |
| 6 | 6 | ~15 | 1 | ~25 |
| **TOTAL** | **31** | **~112** | **9** | **~200** |

From ~150 tools → ~260 tools. From 19 skills → 28 skills.

## Execution order this session

Starting Phase 1 now. Each phase is an independent PR series so partial completion is still useful. Phase 1–2 can run in parallel once ArgoCD + K8s diag tools exist (Phase 2 tools don't depend on them but their tests may exercise cluster state).
