# Operator Backlog (post-2026-05-04 sprint)

> Single source of truth for everything that's BLOCKED ON A HUMAN DECISION
> after the 28-PR production-truthfulness sprint of 2026-05-04. Every
> item below is unblocked from the engineering side; what's missing is
> a vendor pick, a budget approval, a config flip, or a manual operation.
>
> **Read this first** when picking the work back up. Then read
> [docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md)
> for the full north-star plan (Phases 0–6), then
> [ROADMAP.md](../ROADMAP.md) for product phase context and
> [CHANGELOG.md](../CHANGELOG.md) for what shipped.
>
> **Doc truth remediation (2026-05-30):** Port, health, and count claims
> were reconciled against code + prod. Canonical reference:
> [docs/PORTS.md](PORTS.md). Config fixes (`PUBLIC_APP_URL`, `CORS_ORIGINS`,
> gateway HTTP probes) ship in-repo — run `./scripts/verify-doc-truth.sh`
> after Enclii promote; A2A url check passes only post-deploy.

---

## How to use this doc

Each item lists:
- **What** — concrete action to take
- **Why blocking** — what stays broken / degraded until it's done
- **Owner** — who decides / executes
- **Unblocks** — what becomes possible after this lands
- **Cross-refs** — the RFCs / runbooks / PRs with the detail

Items are roughly priority-ordered. Highest value at top.

**Program mapping:** Tier 1–3 items = [Autonomous Operations Program Phase 0](AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-0--operational-foundation-2-3-weeks). Tier 5 items = Program Phases 4–5. Completing Phase 0 gates Phase 1 (live revenue loop).

---

## Tier 1 — Blocks production observability (do first)

### 1. Wire OTel exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`)

- **What**: Pick a backend, provision the endpoint URL + auth header,
  set the env var on every service in production K8s. Verify a trace
  flows end-to-end for one request path (e.g.,
  `POST /api/v1/swarms/dispatch` → worker pickup → checkpoint write).
- **Why blocking**: Today there are zero distributed traces in
  production. SLO dashboards (`infra/grafana/dashboards/selva-slos.json`),
  burn-rate alerts (`infra/prometheus/alerting-rules.yml`), and the
  load-test runbook all become useful only once traces flow. PR #137
  wired the propagation; PR #129 + #139 wired the SLO definitions +
  rules; this is the missing link.
- **Owner**: Operator decides vendor; engineer executes wiring (~1 day
  after decision).
- **Unblocks**: Cross-service trace correlation, SLO dashboards going
  live, burn-rate alerts firing on real data.
- **Cross-refs**:
  - [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
    — recommendation: Grafana Cloud Free → Pro for traces+logs+metrics
  - [docs/SLOS.md](SLOS.md) §8 — implementation cross-refs
  - PR #137 (W3C trace propagation), #129 (SLO defs), #139 (rules + dashboard)

### 2. Provision Sentry per-service DSNs

- **What**: Create 5 separate Sentry projects (nexus-api, workers,
  gateway, colyseus, office-ui), grab the DSN for each, set the
  per-service env var (`SENTRY_DSN`). Add source-map upload to the
  office-ui CI build step. Trigger a synthetic `RuntimeError` in
  staging to verify capture.
- **Why blocking**: Today `init_sentry()` runs in every service but
  the DSNs are unset, so errors don't flow. Production incident
  visibility is ~0 outside of K8s pod logs.
- **Owner**: Operator decides plan; engineer wires up to ~1 day.
- **Unblocks**: Production error capture; Sentry alerts; release
  health tracking.
- **Cross-refs**:
  - [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
    — recommendation: Sentry Team plan EU region (~$26/mo)
  - 5 separate projects so error budgets don't pollute each other

---

## Tier 2 — Blocks billing / compliance correctness

### 3. Populate `STRIPE_PRICE_TO_TIER_MAP`

- **What**: Log into Stripe Dashboard, copy the production price IDs
  for `starter`, `professional`, `enterprise` tiers. Set the JSON map
  in production K8s secret. Restart `nexus-api`.
- **Why blocking**: Empty map means every Stripe subscription event
  falls back to `DEFAULT_TIER` (starter), so live billing would
  mis-tier every customer until corrected. Currently
  `FEATURE_STRIPE_MXN_LIVE=false` so this isn't shipping incorrect
  data — but the feature can't be flipped on until this is set.
- **Owner**: Operator (Stripe Dashboard access required).
- **Unblocks**: `FEATURE_STRIPE_MXN_LIVE=true` in production. Live
  Stripe webhook processing per PR #116.
- **Cross-refs**:
  - PR #116 (Stripe webhook handlers)
  - `apps/nexus-api/nexus_api/config.py:Settings.stripe_price_to_tier_map`
  - `infra/pricing/selva-tiers.json` — references which env key per tier

### 4. Flip `AUDIENCE_FILTER_ENABLED=true` — **DONE (prod)**

- **Status**: Production configmap sets `AUDIENCE_FILTER_ENABLED: "true"`
  (`infra/k8s/production/configmap.yaml`). Platform/tenant boundary is
  enforced on workers + nexus-api.
- **Verify**: No spike in legitimate-traffic 403s; spot-check
  `audience_shadow_block` logs are absent under enforce mode.
- **Cross-refs**:
  - [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md) § Production status
  - Shadow procedure still applies when standing up **new** environments.

---

## Tier 3 — Validates resilience claims

### 5. Run k6 100-concurrent-tasks load scenario in staging

- **What**: Provision `k6` in the operator workstation or staging
  CI runner. Provision a staging API token. Run
  `k6 run -e BASE_URL=https://staging-api.selva.town -e AUTH_TOKEN=<token> tests/load/concurrent-100-swarmtasks.js`.
  Capture summary output. Fill in the Results table in
  `docs/LOAD_TEST_2026-Q2.md`. Adjust production config based on
  observed values.
- **Why blocking**: Today's `MAX_CONCURRENT_TASKS=3`,
  `dispatch_rate_limit=10`, `TIER_DAILY_TASK_LIMIT.{starter,pro,enterprise}=50/200/1000`
  are guesses. The next pricing or scaling decision is uncalibrated.
- **Owner**: Operator (staging access).
- **Unblocks**: Data-driven production limits; SLO calibration;
  pricing decisions backed by evidence.
- **Cross-refs**:
  - PR #128 (scenario + runbook)
  - [docs/LOAD_TEST_2026-Q2.md](LOAD_TEST_2026-Q2.md)
  - [docs/SLOS.md](SLOS.md) §2 — Tier 1 p99 < 1500ms target this
    scenario validates

### 6. Run backup/restore drill in staging

- **What**: Take a fresh prod backup with `make db-backup`. Restore
  it into a clean staging instance with `make db-restore`. Measure
  RTO. Verify off-site/cross-region storage destination. Document RPO.
  Schedule recurring monthly drill.
- **Why blocking**: Today `Makefile` has the targets but no evidence
  of regular testing. The "what's our RTO if we lose the DB tomorrow"
  question is unanswered.
- **Owner**: Operator (production backup access + staging restore).
- **Unblocks**: Confidence in disaster recovery; SOC 2 + LFPDPPP audit
  evidence.
- **Cross-refs**:
  - `Makefile` `db-backup` / `db-restore` / `db-verify-backup` targets
  - `infra/k8s/production/backup-cronjob.yaml`
  - RFC 0021 §10 — failover RFC depends on backup evidence

---

## Tier 4 — Schedule the recurring rituals

### 7. Schedule first quarterly secret rotation

- **What**: Pick the first Tuesday of the next quarter (Q3 2026 →
  2026-07-07 14:00 MX). Add to ops calendar with the runbook link.
  Run `./scripts/rotate-secret.sh --all --namespace=autoswarm` from
  a workstation with `kubectl` access + bash 4+. Now safely includes
  `consent-ledger-signing` (PR #145 closed the §6 limitation).
- **Why blocking**: Three production secrets (`WORKER_API_TOKEN`,
  `CONSENT_LEDGER_SIGNING_SECRET`, `COLYSEUS_SERVICE_TOKEN`) have
  never been rotated. SOC 2 CC6.1 cadence is 90d. The validators
  catch "I forgot to set this" but not "I set this 12 months ago."
- **Owner**: Operator (kubectl access + brew bash on macOS).
- **Unblocks**: SOC 2 CC6.1 compliance evidence; reduced blast
  radius from any single-key compromise.
- **Cross-refs**:
  - [docs/SECRET_ROTATION_POLICY.md](SECRET_ROTATION_POLICY.md)
  - `scripts/rotate-secret.sh` — atomic rotation tool
  - PR #138 (script + policy), PR #145 (per-period key tracking
    that made consent-ledger-signing safe to rotate)

### 8. Quarterly SLO review

- **What**: Pick a date 90 days out (next: 2026-08-04). Walk through
  [docs/SLOS.md](SLOS.md) §7 checklist: did we hit each SLO over the
  last 90d? Were burn-rate alerts noisy? Reclassify endpoints? Add
  new endpoints to §4? Output: `docs/SLO_REVIEW_2026Q3.md`.
- **Why blocking**: SLOs that aren't reviewed drift into uselessness.
  A doc that nobody updates becomes a doc nobody reads.
- **Owner**: Engineer-led with operator review.
- **Unblocks**: Trustworthy production SLO commitment.
- **Cross-refs**: [docs/SLOS.md](SLOS.md) §7

---

## Tier 5 — Architecture (multi-week implementations behind RFCs)

### 9. Approve Kafka cluster + cost for CDC RFC #0019

- **What**: Decide where the audit Kafka cluster lives (existing
  `internal-devops` K8s vs dedicated). Approve the ~$300-800/mo
  cost (managed AWS MSK + Confluent Schema Registry + Kafka Connect
  workers). Then engineer can execute Phase A pilot (Selva CDC) in
  ~2 weeks.
- **Why blocking**: Manual `emit_event_db` discipline doesn't scale
  past 6+ services. Without CDC, cross-service audit queries (per
  RFC §1 examples) remain unanswerable.
- **Owner**: Operator (cost approval + cluster ownership decision).
- **Unblocks**: 10-week phased CDC migration per RFC §4. Eventually
  retires the manual `emit_event_db` discipline (PR #130/131/133)
  in favor of automatic per-row CDC capture.
- **Cross-refs**: [docs/rfcs/0019-cross-service-cdc-audit-topic.md](rfcs/0019-cross-service-cdc-audit-topic.md)

### 10. Provision MX-region cluster for residency RFC #0020

- **What**: Stand up a Postgres + Redis + K8s cluster in a Mexican
  AWS / GCP region. Plumb `DATABASE_URL_MX` env var. Engineer
  executes the per-region routing helper + `tenant_configs.data_residency_region`
  ENUM column + onboarding flow per RFC §4.
- **Why blocking**: Mexican LFPDPPP / SAT requirements for CFDI
  data residency are active. New SAT-bound tenants today land in
  whatever region the single shared cluster lives in. First
  enforcement audit would surface this gap.
- **Owner**: Operator (cluster provisioning) + engineer
  (implementation, ~3-4 weeks).
- **Unblocks**: SAT-compliant onboarding for new Mexican tenants.
  Then RFC 0021 multi-region failover becomes implementable.
- **Cross-refs**:
  - [docs/rfcs/0020-per-tenant-data-residency.md](rfcs/0020-per-tenant-data-residency.md)
  - [docs/rfcs/0021-multi-region-failover.md](rfcs/0021-multi-region-failover.md)

### 11. Cut over A2A bridge to per-caller tenants (RFC #0018 Phase D)

- **What**: Migration 0029 (PR #136) scaffolded `external_a2a_callers`
  table. Now write the bridge cutover: `_dispatch_a2a_task` and
  `_get_a2a_task_status` in `apps/nexus-api/nexus_api/main.py`
  switch from `tenant_session(org_id="a2a-external")` to looking up
  the per-caller tenant row by `agent_card_url`. Migrate any
  in-flight `a2a-external` rows.
- **Why blocking**: Today every A2A caller shares the synthetic
  `a2a-external` org. No quota / billing / consent / per-caller
  audit. Acceptable for 0 paying A2A callers; broken on first one.
- **Owner**: Engineer (~1 week implementation behind RFC).
- **Unblocks**: Real A2A monetization + per-caller observability +
  per-caller revocation.
- **Cross-refs**: [docs/rfcs/0018-a2a-external-tenant-model.md](rfcs/0018-a2a-external-tenant-model.md) §4 Phase D

---

## Tier 6 — One-off operator merges

### 12. Merge PR #125 (mypy wave 7) — **DONE**

- **Status**: Merged to `main` (2026-05-04). Packages mypy ratchet is 0.

---

## Index of related docs (for orientation)

| File | Purpose |
|---|---|
| [AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md) | **North star** — Phases 0–6 toward full autonomous digital ops |
| [ROADMAP.md](../ROADMAP.md) | Honest scorecard + product phases (F/E). Read after this doc. |
| [CHANGELOG.md](../CHANGELOG.md) | What shipped. v2.3.0 entry covers today's work. |
| [CLAUDE.md](../CLAUDE.md) | Patterns + invariants reference. "Patterns Added in v2.3.0" section is the most current. |
| [docs/SLOS.md](SLOS.md) | Per-endpoint SLO definitions + burn-rate alert specs. |
| [docs/SECRET_ROTATION_POLICY.md](SECRET_ROTATION_POLICY.md) | Quarterly cadence + procedure. |
| [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md) | Operator vendor decision. |
| [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md) | Shadow-soak procedure for the audience flip. |
| [docs/LOAD_TEST_2026-Q2.md](LOAD_TEST_2026-Q2.md) | k6 scenario runbook + results template. |
| [docs/AUDIT_TRAIL_GAP_ANALYSIS.md](AUDIT_TRAIL_GAP_ANALYSIS.md) | SUPERSEDED. Historical gap inventory. |
| [docs/RLS_PHASE_1_5_AUDIT.md](RLS_PHASE_1_5_AUDIT.md) | RLS audit. Closed by PRs #114, #126, #134. |
| [docs/rfcs/0017-image-digest-pinning.md](rfcs/) | Image digest pinning (PR #86 still open). |
| [docs/rfcs/0018-a2a-external-tenant-model.md](rfcs/0018-a2a-external-tenant-model.md) | A2A external tenant. Phase D cutover pending. |
| [docs/rfcs/0019-cross-service-cdc-audit-topic.md](rfcs/0019-cross-service-cdc-audit-topic.md) | CDC audit topic. Phase A pilot pending operator approval. |
| [docs/rfcs/0020-per-tenant-data-residency.md](rfcs/0020-per-tenant-data-residency.md) | Per-tenant data residency. Implementation pending MX-region cluster. |
| [docs/rfcs/0021-multi-region-failover.md](rfcs/0021-multi-region-failover.md) | Multi-region failover. Implementation pending RFC 0020 topology. |
| [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md) | Phase 2 campaign contract (Tulana ↔ Selva ↔ Phynd) |

---

## Picking this work back up — recommended reading order

1. **This doc** — what's blocked + why
2. **[AUTONOMOUS_OPERATIONS_PROGRAM.md](AUTONOMOUS_OPERATIONS_PROGRAM.md)** — north star + phase gates
3. **ROADMAP.md "Honest scorecard"** — where we actually are
4. **CHANGELOG.md** — what shipped
5. **The RFC or contract for whichever phase you're executing**

If you're picking up after several weeks: also check `git log --oneline -30`
for any new merges and `gh pr list --state open` for any new PRs that
weren't here at the end of 2026-05-04.
