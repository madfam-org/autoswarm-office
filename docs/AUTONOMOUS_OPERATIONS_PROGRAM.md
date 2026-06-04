# Autonomous Operations Program — North Star to 100%

> **Status:** Accepted program plan (2026-05-30)
> **Owner:** MADFAM platform operator + Selva engineering
> **Scope:** Full remediation and implementation toward autonomous,
> revenue-generating, campaign-planning, compliance-grade, multi-product
> orchestration for the MADFAM tenant slice (`PLATFORM_ORG_ID=madfam`,
> `admin@madfam.io`) and downstream customer tenants.

---

## How this doc relates to others

| Doc | Role |
|-----|------|
| **This doc** | North-star definition, phased program, exit gates, scorecard targets |
| [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md) | **Commercial GA contract** — no-go gates, immediate hardening, evidence checklist |
| [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) | **Sprint plan** — 4-week remediation schedule + engineering backlog |
| [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) | Human-gated items within Phase 0–1 (OTel, Sentry, Stripe map, k6, DR) |
| [ROADMAP.md](../ROADMAP.md) | Product phases (F1–F5, E1–E6), honest scorecard, historical milestones |
| [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](./TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md) | Phase 2 campaign contract (Tulana → Selva → Phynd → Tulana) |
| [rfcs/phygital-quote-truth-contract.md](./rfcs/phygital-quote-truth-contract.md) | Phase 3 quote-truth invariants |
| [SLOS.md](./SLOS.md) | Observability targets; dashboards activate in Phase 0 |
| [PP_4_STAGING_AUDIT.md](./PP_4_STAGING_AUDIT.md) | Staging tier; Phase 0 completion checklist |

---

## North star (definition of “100%”)

MADFAM runs as a **closed-loop digital operator** through Selva when all of
the following are true:

| Capability | Done when |
|------------|-----------|
| **Autonomous** | Gateway + workers execute ranked work (CRM, campaigns, billing, ops) with **graduated HITL** — routine lanes do not require manual dispatch |
| **Revenue-generating** | Hot lead → draft → approve → send → checkout → subscription → invoice (CFDI) is **traced end-to-end** with attribution |
| **Campaign-planning** | Tulana SKU packs drive ranked campaign lanes; drafts use **proof points only**; Phynd stages/sends; outcomes feed Tulana buyer-signal |
| **Compliance-grade** | Voice/consent ledger, SAT/CFDI paths, LFPDPPP controls, cross-service audit, MX residency option, DR **proven** |
| **Multi-product** | One orchestration layer spans Selva + Phynd + Dhanam + Karafiel + Cotiza/Yantra/Pravara + Tulana (+ Fortuna/Tezca where cited) |

### Baseline (2026-05-30)

| Scope | Estimate | Notes |
|-------|----------|-------|
| MADFAM platform slice in Selva | **~85–90%** | Prod live; `PLATFORM_ORG_ID=madfam`; audience filter enforced; 10-agent roster |
| Selva “production-truthful” | **~88–92%** | RLS, audit, idempotency, webhook hardening — see ROADMAP honest scorecard |
| Full north star (this doc) | **~58–65%** | Phase 2 API + UI shipped; API campaign loop proven on staging; Phase 0 + Phase 1 revenue proof remain |

### Readiness update (2026-06-04)

For the **MADFAM tenant slice in prod (`admin@madfam.io`)**, the platform is close enough to unrestricted internal use for daily operator workflows.

- **Current estimate:** ~**85–90%** operationally usable for tenant-slice work.
- **Commercial GA estimate (all tenants):** ~**58–65%**.
- **Primary blockers to full commercial GA:** cross-service tenant propagation,
  gateway dispatch contract correctness, OTel/Sentry proof, Dhanam
  pricing/webhook attribution closure, `k6` Run 4b validation, and DR evidence.
- **Decision rule:** do not treat campaign features as “GA” until the
  commercial-GA no-go gates, Phase 0 gates, and one attributable paid
  conversion are proven end-to-end.

This same sequence is tracked in:

- [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) (execution checklist and sprints)
- [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) (operator gating)
- [ROADMAP.md](../ROADMAP.md) (overall scorecard)
- [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md) (commercial GA acceptance checklist)

---

## Commercial GA no-go gates (2026-06-04)

The north-star program now has a platform-wide commercial GA contract:
[COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md).
The short form is:

| Gate | Must be true before broad tenant GA |
|------|-------------------------------------|
| Tenant propagation | Gateway, workers, Colyseus, and other service-token paths carry explicit tenant context |
| Dispatch contracts | Automated dispatch rules use only API-accepted graph types with real worker support |
| Observability | OTel traces, Sentry errors, SLO dashboards, and alert owners are live |
| Money path | Dhanam price-tier mapping, webhooks, attribution, and invoice/CFDI evidence are proven |
| Resilience | Load thresholds pass and restore drills have measured RTO/RPO |
| Product live paths | No placeholders, fake recipients, or demo fallbacks remain on live tenant paths |
| Governance | Consent, HITL, audit, A2A tenancy, and residency answers are available per target buyer class |

---

## Five control planes

Every phase advances one or more planes. **Autonomy without governance is out of scope.**

```text
Evidence (Tulana)     → SKU readiness, proof points, do_not_claim
Orchestration (Selva) → Gateway, workers, graphs, permission matrix, budget gate
Execution (ecosystem) → Phynd, Dhanam, Karafiel, Cotiza, Yantra4D, Pravara, …
Governance            → Consent/voice, audience filter, RLS, CDC audit, residency
Observability         → OTel, Sentry, SLO burn alerts, on-call runbooks
```

---

## Phase 0 — Operational foundation (2–3 weeks)

**Goal:** Prod and staging trustworthy enough to run money and campaigns on.

| ID | Work | Primary repo | Exit criteria |
|----|------|--------------|---------------|
| 0.1 | Wire `OTEL_EXPORTER_OTLP_ENDPOINT` on all 6 services | selva-office + Enclii | **Partial** — K8s secret refs + deterministic trace verifier shipped; operator provisions Grafana token → end-to-end trace |
| 0.2 | Sentry DSNs + office-ui source maps in CI | selva-office | **Partial** — source-map upload wiring shipped; synthetic staging error captured after DSNs/auth token are provisioned |
| 0.3 | Dhanam price→tier map + Selva webhook verification | Dhanam + selva-office | **Partial** — Selva handler + strict verifier green at repo level; Dhanam catalog keys and durable fan-out evidence still needed |
| 0.4 | k6 100-concurrent-tasks in staging | selva-office | **Partial** — Runs 1–4 failed thresholds; Run 4b `staging-load` overlay + live preflight shipped; threshold pass pending ([plan](./PHASE_0_REMEDIATION_PLAN.md)) |
| 0.5 | Backup/restore drill | selva-office + ops | **Partial** — guarded drill wrapper + evidence verifier shipped; no executed drill evidence yet |
| 0.6 | Staging completion | selva-office + Janua | **Partial** — namespace live; Janua staging OAuth pending |
| 0.7 | First quarterly secret rotation | ops | **Partial** — Q3 schedule record/verifier shipped; external calendar confirmation + execution evidence pending |
| 0.8 | Commercial-GA correctness hardening | selva-office | ✅ Repo-level closure — GA-001..GA-008 implemented/tested or documented; operational rollout evidence remains in Phase 0 |

**Maps to:** [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) Tier 1–3 (items 1–6).

**Gate to Phase 1:**

- `./scripts/verify-doc-truth.sh` green on prod
- `./scripts/staging-smoke.sh` green
- OTel + Sentry receiving data
- Stripe tier map verified in staging **via Dhanam webhooks**
- Commercial-GA correctness gate 0.8 complete:
  - no service-token path falls back to `platform` unintentionally
  - gateway auto-dispatch rules match API `graph_type` contract
  - live outbound/campaign paths have no placeholder recipients

---

## Phase 1 — Closed revenue loop (3–4 weeks)

**Goal:** ROADMAP Phase F1 **live**, not code-complete.

```text
Heartbeat → PhyndCRM hot leads → auto-dispatch (HITL)
  → CRM graph email → Resend → Dhanam checkout CTA
  → Stripe subscription → Karafiel invoice (CFDI)
```

| ID | Work | Exit criteria |
|----|------|---------------|
| 1.1 | Provider budget | LLM credits + `packages/budget-gate` wired with org-level caps |
| 1.2 | Dhanam compute budgets | ✅ Dispatch/check-budget resolve tier via Redis → `tenant_configs.subscription_tier`; block `past_due` |
| 1.3 | Attribution closure | `utm_campaign` + checkout reattribution tested prod → CRM → Dhanam |
| 1.4 | Live Stripe path | Flip `FEATURE_STRIPE_MXN_LIVE` after 0.3; verify 5 webhook event types |
| 1.5 | Voice/consent on outbound | Every marketing send: voice_mode + ledger row; agent_identified SPF check |
| 1.6 | Graduated HITL baseline | All lanes ASK initially; document promotion criteria (Phase 6) |

**Gate to Phase 2:** One paid conversion traced: CRM `lead_id` → Stripe `customer_id` → `tenant_configs` tier → invoice/CFDI artifact.

---

## Phase 2 — Campaign planning & execution (4–6 weeks)

**Goal:** Implement [TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md](./TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md).

| ID | Deliverable | Implementation |
|----|-------------|----------------|
| 2.1 | Tulana import API | ✅ `POST /api/v1/campaigns/import-tulana-pack` + schema validation (`routers/campaigns.py`) |
| 2.2 | `sku_campaign_planning` | ✅ `campaign` graph (`load_tulana_pack` → `plan_lane` → `draft_copy`); import dispatches `graph_type=campaign` |
| 2.3 | `campaign_draft` | ✅ `campaign` graph drafts from proof points; `guard_campaign_draft()` scrubs `do_not_claim`; auto `schedule_social` after `draft_copy` |
| 2.4 | Phynd handoff | ✅ `POST /api/v1/campaigns/crm-handoff` with idempotency + HITL |
| 2.5 | Scheduled social executor | ✅ Enqueue API + `POST /campaigns/schedule-social`; worker drain (`social_post_executor`); **`schedules` cron materializer** → `scheduled_actions` |
| 2.6 | Feedback loop | ✅ `POST /api/v1/campaigns/tulana-feedback` → Tulana buyer-signal API |
| 2.7 | Campaign UI | ✅ Office **Campaign Dashboard** (`/office` → Campaigns): Tulana import, task lane, HITL social queue, CRM handoff, Tulana feedback, readiness badges |

**Permission policy:** Campaign sends stay **ASK** until lane has 30 days zero incidents; operator promotes specific lanes to ALLOW.

**Gate to Phase 3:** ✅ API path proven (`verify-campaign-loop.sh --staging`). Optional UI soak on `/office` → Campaigns. Then begin phygital graph (Phase 3).

---

## Phase 3 — Multi-product phygital orchestration (6–8 weeks)

**Goal:** ROADMAP Phase F3 + [phygital-quote-truth-contract.md](./rfcs/phygital-quote-truth-contract.md).

| ID | Work | Exit criteria |
|----|------|---------------|
| 3.1 | `phygital.py` LangGraph | design → quote → HITL approve → work order → ship → invoice |
| 3.2 | Quote truth enforcement | `require_market_verified: true`; fail on `market_verified: false` |
| 3.3 | Webhook hardening | Cotiza ↔ Yantra4D ↔ Pravara under idempotency + audit events |
| 3.4 | Karafiel invoice node | Billing graph stamps CFDI after Dhanam payment |
| 3.5 | Operator demo | Recorded E2E: upload → quote → approve → MES WO → invoice PDF |

**Cross-repo:** cotiza, yantra4d, pravara-mes, karafiel, dhanam — Selva orchestrates; siblings own SLAs.

---

## Phase 4 — Compliance-grade platform (6–10 weeks, parallel with 2–3)

**Goal:** SAT + LFPDPPP + audit defensibility for enterprise and government buyers.

| Track | Selva work | Sibling |
|-------|------------|---------|
| SAT extensions | Constancia lookup + complemento de pagos tools | karafiel |
| LFPDPPP | PII tagging, deletion workflow, aviso generator, cross-border flags | tezca |
| Audit CDC | RFC 0019 Phase A: Postgres → Kafka → audit topic | internal-devops |
| Residency | RFC 0020 MX cluster + `data_residency_region` | enclii |
| Failover | RFC 0021 after 0020 topology | enclii |
| Legal surfaces | `selva.town/terms`, `/privacy`, `madfam.io/unsubscribe` | madfam-site |

**Gate:** Auditor can show consent for an email, audit trail for an invoice, and tenant data region.

**Maps to:** [OPERATOR_BACKLOG.md](./OPERATOR_BACKLOG.md) Tier 5 (items 9–11), ROADMAP Phase E2.

---

## Phase 5 — Full multi-tenant autonomy at scale (8–12 weeks)

**Goal:** MADFAM on platform org; **customers** self-provision with same rigor.

| ID | Work | Exit criteria |
|----|------|---------------|
| 5.1 | Enterprise SSO | Janua OIDC per-tenant `org_id` mapping |
| 5.2 | White-label | Per-tenant branding + custom domain via Enclii |
| 5.3 | Tenant isolation audit | RLS + Redis prefix + Colyseus formal report |
| 5.4 | A2A Phase D | Per-caller tenants (RFC 0018); quota + billing |
| 5.5 | Intelligence APIs | Fortuna/Tezca/Forgesight behind Selva proxy + Dhanam metering |
| 5.6 | Self-provisioning GTM | Karafiel wedge: pricing page, 10 paying customers, referral flywheel |

**Maps to:** ROADMAP Phases F2, F4, F5, E1, E6.

---

## Phase 6 — Autonomy graduation (ongoing from Phase 1)

**Goal:** Policy-driven ASK → ALLOW without safety regressions.

| Lane | Initial | Graduate to ALLOW when |
|------|---------|------------------------|
| CRM hot-lead email draft | ASK | 30d, 0 consent violations, <1% LLM placeholder aborts |
| Tulana campaign drafts | ASK | Contract tests green + operator sign-off per SKU |
| Social POST (Reddit/Mastodon/Bluesky) | ASK | Playbook + disclosure + rate limit proven |
| LinkedIn | Draft-only | **Never auto-post** — manual paste only |
| CFDI stamp | ASK | Karafiel prod hardening + SAT test org |
| Deploy / Enclii ops | ASK | Platform org only; never tenant |

Instrument: SLO burn rates, `audience_mismatch` alerts, consent-ledger verification, budget-gate tripwires.

See [HITL_FLOW.md](./HITL_FLOW.md) and permission matrix in `packages/permissions/`.

---

## Program structure

### Workstreams

| Stream | Phases | Key repos |
|--------|--------|-----------|
| Ops & observability | 0 | selva-office, enclii, internal-devops |
| Revenue & billing | 1 | selva-office, dhanam, phynd-crm |
| Campaign orchestration | 2 | selva-office, tulana, phynd-crm |
| Phygital | 3 | selva-office, cotiza, yantra4d, pravara-mes |
| Compliance & audit | 4 | selva-office, karafiel, tezca, internal-devops |
| Platform GTM | 5 | selva-office, janua, madfam-site |

### Cadence

| Ritual | Frequency | Doc |
|--------|-----------|-----|
| Operator backlog review | Weekly | OPERATOR_BACKLOG |
| Autonomy graduation board | Biweekly | This doc § Phase 6 |
| SLO review | Quarterly | SLOS §7 |
| Secret rotation | Quarterly | SECRET_ROTATION_POLICY |
| Backup drill | Monthly | DISASTER_RECOVERY |

### Critical path

```text
Phase 0 (ops) ──► Phase 1 (revenue live)
                      │
                      ├──► Phase 2 (campaigns) ──► Phase 6 (graduation)
                      │
                      └──► Phase 3 (phygital) ──► Phase 5 (multi-tenant GTM)

Phase 4 (compliance) parallel from week 2; gates Phase 5 enterprise sales.
```

### First 30 days (highest ROI) — updated 2026-06-04

**Done:** Phase 2 API + UI (#179); staging campaign loop; Tulana buyer-signal;
load-test harness and calibration graph (Runs 1–4); Wave 0 commercial-GA
correctness GA-001..GA-008 at repo level.

**Remaining (see [COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](./COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md)
and [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md)):**

1. **Sprint 0:** OTel + Sentry secrets; Dhanam price map + durable webhook fan-out
2. **Sprint 1:** k6 Run 4b; backup/restore drill
3. **Sprint 2:** Phase 1 revenue proof on staging → `promote-to-prod.yml`
4. **Sprint 3:** Campaign UI soak; Phase 3 phygital scaffold

---

## Scorecard targets (program completion)

| Dimension | Baseline → Target | Primary phase |
|-----------|-------------------|---------------|
| Cross-service tenant propagation | 75% → **100%** | 0.8 |
| Observability traces | 70% → **95%** | 0 |
| Cross-service audit | 20% → **90%** | 4 |
| Concurrency under load | 50% → **85%** | 0 |
| Backups + DR | unknown → **90%** | 0 |
| Deployment pipeline | ~85% → **90%** | 0 (PP.5 prod cutover) |
| Autonomous revenue loop | code-complete → **live** | 1 |
| Campaign orchestration | API + UI shipped → **proven API loop** | 2 |
| Phygital E2E | webhooks only → **demo** | 3 |
| Compliance GTM | tools → **paying + LFPDPPP** | 4–5 |
| Multi-tenant scale | provisioning API → **SSO + 100 orgs** | 5 |

**Program target:** ~**95%+** of north star in **6–9 months** with parallel streams. **100%** additionally requires Phase 5 GTM traction (paying customers, unit economics) — partly market, not engineering alone.

---

## Risks and non-goals

| Risk | Mitigation |
|------|------------|
| Service-token tenant ambiguity | Commercial GA gate 0.8; every service-token call carries explicit org context |
| Autonomy before observability | Phase 0 is a hard gate |
| Campaign hallucination | Tulana contract + `do_not_claim` CI |
| Cross-repo drift | Idempotency + CDC audit (RFC 0019) |
| Cost explosion | Budget gate + dispatch caps + Dhanam tiers |
| Compliance theater | Consent ledger + voice mode fail-closed |

**Non-goals for “100%”:**

- LinkedIn auto-posting (draft-only forever by design)
- Full labor-law automation (ROADMAP E2 HR — separate multi-quarter program)
- $500K MRR (business outcome, not an engineering deliverable)

---

## Epic breakdown (engineering)

Use these as PR/epic titles when executing:

| Epic | Phase | Acceptance source |
|------|-------|-------------------|
| `epic/commercial-ga-correctness` | 0.8 | COMMERCIAL_GA_REMEDIATION_PLAN GA-001..GA-008 |
| `epic/ops-foundation` | 0 | OPERATOR_BACKLOG + verify-doc-truth + staging-smoke |
| `epic/revenue-loop-live` | 1 | ROADMAP F1 gate + attribution tests |
| `epic/tulana-campaign-orchestration` | 2 | TULANA_SKU doc § Tests and acceptance |
| `epic/phygital-graph` | 3 | phygital-quote-truth-contract + ROADMAP F3 |
| `epic/compliance-grade` | 4 | OPERATOR_BACKLOG 9–11 + ROADMAP E2 |
| `epic/multi-tenant-gtm` | 5 | ROADMAP E1 + F5 |
| `epic/autonomy-graduation` | 6 | Phase 6 table + HITL_FLOW |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-04 | Added commercial GA contract, no-go gates, Phase 0.8 correctness hardening, and updated first-30-days plan |
| 2026-05-30 | [PHASE_0_REMEDIATION_PLAN.md](./PHASE_0_REMEDIATION_PLAN.md) — 4-sprint remediation schedule; Run 4 plan; Enclii gap registry |
| 2026-05-30 | Phase 2.7 Campaign Dashboard + schedule materializer + campaign graph auto-schedule merged (#179); staging API loop green |
| 2026-05-30 | Initial program plan documented; staging bootstrap + DNS fix landed on main |
