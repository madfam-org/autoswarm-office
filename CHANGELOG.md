# Changelog

All notable changes to **Selva Office** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **`prepare_social_post_schedule_payload`** — `POST /api/v1/schedules/` with
  `action=social_post` auto-injects JWT `org_id` and validates platform fields
  for the worker schedule materializer.
- **`scripts/verify-campaign-path.sh`** — auth-gate smoke for Phase 2 campaign
  routes (wired into `verify-phase0-gates.sh --staging`).
- **Phase 2.7 Campaign Dashboard** — office-ui modal at `/office` → **Campaigns**
  (HUD + Dashboard panel): Tulana JSON import, campaign task lane, scheduled
  social HITL approve/deny, CRM handoff, Tulana feedback push, GA readiness badges.
  Components: `apps/office-ui/src/components/campaigns/`.
- **Schedule materializer** — worker job `schedule_materializer.py` bridges
  `schedules` cron rows (`action=social_post`) → `scheduled_actions` queue
  (runs every 60s alongside `social_post_executor`).
- **Campaign graph auto-schedule** — `schedule_social` node after `draft_copy`
  enqueues HITL-gated social cadence via `POST /api/v1/campaigns/schedule-social`
  (disable with `auto_schedule_social: false` in task payload).
- **Phase 2.5 scheduled social enqueue** — `ScheduledActionRow` model,
  `POST /api/v1/scheduled-actions`, batch + HITL approve, and
  `POST /api/v1/campaigns/schedule-social` for Tulana cadence posting.
- **k6 load-test workflow** — `.github/workflows/load-test.yml` (`workflow_dispatch`).
- **`scripts/verify-dhanam-billing-path.sh`** — staging/prod Dhanam-first checks.
- **Phase 1.2 tier enforcement** — `resolve_org_daily_limit()` reads Redis cache then
  `tenant_configs.subscription_tier`; dispatch blocks `past_due`/`cancelled` subscriptions.
- **`POST /api/v1/campaigns/tulana-feedback`** — pushes campaign outcomes to Tulana
  buyer-signal API (Phase 2.6).
- **Dhanam-first billing sync** — `billing_sync.py` handles
  Dhanam-normalized subscription/invoice events; `POST /api/v1/billing/webhooks/dhanam`
  fail-closed without `DHANAM_WEBHOOK_SECRET`; direct Stripe webhook returns 503 when
  `BILLING_VIA_DHANAM=true` (default).
- **`POST /api/v1/campaigns/crm-handoff`** — HITL-gated Phynd CRM staging for
  approved Tulana campaign drafts (Phase 2.4).
- **`campaign` worker graph** — Tulana SKU planning lane + draft generation with
  `do_not_claim` guardrail scrubbing (Phase 2.2–2.3).
- **Phase 0 observability k8s wiring** — optional `autoswarm-observability-secrets`
  env refs on all 6 Deployments + `observability-secrets-template.yaml` +
  `./scripts/verify-phase0-gates.sh`.
- **OTel gRPC exporter deps** on nexus-api and workers (activates when endpoint set).
- **`POST /api/v1/campaigns/import-tulana-pack`** — Tulana SKU pack validation,
  ranking, optional `dispatch_tasks` for `sku_campaign_planning` on the
  `intelligence` graph (Phase 2.1–2.2).
- **Staging KEDA pin** — `patch-keda-staging.yaml` sets workers `maxReplicaCount: 1`
  so RWO `selva-memory-pvc` does not Multi-Attach when KEDA scales past one pod.
- **[Autonomous Operations Program](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md)** — canonical
  north-star plan (Phases 0–6): operational foundation, live revenue loop, Tulana
  campaign orchestration, phygital E2E, compliance-grade platform, multi-tenant GTM,
  autonomy graduation. Cross-linked from ROADMAP, OPERATOR_BACKLOG, README,
  ECOSYSTEM, llms.txt, RFC index, and Tulana campaign contract.

### Changed
- **Staging/prod Dhanam wiring** — nexus-api gets `DHANAM_WEBHOOK_SECRET` + staging
  `DHANAM_API_URL=https://staging-api.dhan.am`; secrets template documents bootstrap key.
  scorecard links north-star gap to AUTONOMOUS_OPERATIONS_PROGRAM.
- **OPERATOR_BACKLOG.md** — Tier 1–3 mapped to Program Phase 0; reading order updated.
- **docs/rfcs/README.md** — index for RFCs 0018–0021 and phygital quote-truth contract.

## [2.3.0] - 2026-05-04

> Production-truthfulness sprint. 24 PRs in 24h closed every in-repo
> Phase 1, Phase 2, and Phase 3 item that didn't require an operator
> decision. Estimated platform stability moved from ~58% (start of
> session) to ~85% (end). Remaining gap is concentrated in
> operator-gated infra (OTel + Sentry vendor wiring, AUDIENCE_FILTER
> flip, Stripe price→tier map, backup drill execution) and longer-arc
> architecture (per-tenant data residency, multi-region failover, CDC
> audit topic — all RFCs landed).

### Added

#### Persistence + correctness
- **Real PostgresSaver lifecycle** (#123) — closes the silent
  state-loss bug where every worker pod was using `MemorySaver`
  because `PostgresSaver.from_conn_string` is a `@contextmanager`
  not a factory. Now opens a `psycopg_pool.ConnectionPool` (min=1,
  max=4) wired into `PostgresSaver(conn=pool)`. Worker pod restart
  mid-graph now resumes from a real checkpoint instead of restarting
  from scratch. `close_checkpointer()` wired into the graceful drain.
- **`tenant_session(org_id)` helper** (#126) — closes 5 RLS Phase 1.5
  break sites that opened `async_session_factory()` directly without
  setting `app.current_org_id`. Audit middleware, A2A bridge
  helpers, WS initial-batch handlers all migrated. Required
  prerequisite for strict mode.
- **RLS strict mode** (#134, migration 0028) — drops the
  `IS NULL OR = ''` permissive escape hatch from migration 0025's
  policies, applies `FORCE ROW LEVEL SECURITY` on all 18 tenant
  tables, adds `app_admin` BYPASSRLS role, ships `admin_session()`
  helper for cross-tenant ops endpoints, adds
  `GET /api/v1/health/rls-status` for runtime verification.

#### Audit + observability
- **Audit-trail completeness** (#130, #131, #133) — closes 37 of 37
  mutation sites identified in `docs/AUDIT_TRAIL_GAP_ANALYSIS.md`
  across 14 routers (tenants, swarms, agents, workflows,
  marketplace, maps, calendar, schedules, hitl_confidence,
  departments, tenant_identities, artifacts, command_approvals,
  approvals.bulk_expire). New `bulk_expire` endpoint added.
- **W3C trace context propagation** (#137) — `opentelemetry.propagate`
  extract on FastAPI server side, inject on worker→nexus-api hops via
  `selva_workers.auth.get_worker_auth_headers()`, inject on outbound
  HTTP from tools via `_build_safe_request_kwargs`. Stays no-op when
  OTel exporter is unset (operator-gated). 18 new tests pin the
  contract.
- **SLO definitions** (#129) — three-tier endpoint classification with
  per-tier latency / error / availability targets, multi-window
  multi-burn-rate alert specs (Google SRE Workbook ch.5), separate
  task-level SLIs (success rate ≥95% / 7d, DLQ <5 sustained, approval
  queue p95 <2h), quarterly review cadence, per-PR adoption checklist.
- **SLO recording rules + alerts + Grafana dashboard** (#139) — 16
  Prometheus recording rules + 7 multi-window burn-rate alerts + 10
  Grafana panels in `infra/{prometheus,grafana}/`. promtool-validated.
  Becomes useful when OTel exporter is wired.

#### Compliance + ecosystem cohesion
- **Stripe webhook real handlers** (#116) — 5 events
  (`customer.subscription.{created,updated,deleted}`,
  `invoice.{paid,payment_failed}`) mirror state into `tenant_configs`
  via migration 0027 (`stripe_customer_id` UNIQUE+indexed). Refresh
  cached tier limits + emit billing events. 22 regression tests.
  **Operator gate**: populate `STRIPE_PRICE_TO_TIER_MAP` from Stripe
  Dashboard before flipping `FEATURE_STRIPE_MXN_LIVE=true`.
- **`email_inbound` webhook hardening** (#122) — 15/15 webhook
  handlers now fail-closed. Provider-agnostic allow-list pattern via
  `_require_inbound_allowlist`. Trust signal documented.
- **Pricing source-of-truth** (#135) — Tulana decision doc → JSON →
  loader pattern. Canonical data in `infra/pricing/selva-tiers.json`
  (schema-validated). `apps/nexus-api/nexus_api/billing_tiers.py`
  refactored to load from JSON with same exported names + same
  fallback semantics. CI drift gate
  (`tests/test_pricing_codification.py`) catches loader / JSON /
  CLAUDE.md / fallback disagreement.

#### Operator surface
- **Idempotency-Key dependency + adoption** (#127, #141, #142) —
  `Depends(get_idempotency_context)` on 10 mutation endpoints (4
  Tier 1: `dispatch`, `approve`, `deny`, `voice-mode`; 6 Tier 2:
  `marketplace.install`, `calendar.connect`, `maps.create`,
  `maps.import`, `workflows.create`, `workflows.import`).
  Org-scoped Redis cache, 24h TTL, graceful Redis-down degradation.
  53 regression tests across the helper + adoption.
- **Secret rotation tool + policy** (#138) — `scripts/rotate-secret.sh`
  rotates `WORKER_API_TOKEN` / `CONSENT_LEDGER_SIGNING_SECRET` /
  `COLYSEUS_SERVICE_TOKEN` atomically (K8s Secret patch + rolling
  restart + per-pod env verification). `docs/SECRET_ROTATION_POLICY.md`
  defines quarterly cadence + procedure + rollback. Smoke tests in
  `tests/scripts/`. Bash 4+ required (Linux CI ok; macOS dev needs
  brew bash).
- **`reap-stale` tenant-scoping fix** (#114) — was silently scoped
  to one org via the Phase 1 RLS escape hatch (always reaped only
  `org_id="default"`). Now role-gated to service/worker/platform/admin
  and explicitly resets `app.current_org_id` to bypass tenant RLS.
  11 regression tests.

#### Resilience
- **`_cleanup_stale_worktrees` OSError fix** (#113) — surfaced by
  PR #112 coverage push. Worker startup no longer crashes on stale
  NFS / dead-symlink / permission-denied worktrees.
- **`Idempotency-Key` org-scoped Redis cache** prevents cross-tenant
  cache leak and method+path scopes prevent same-key-different-op
  conflation.

#### CI + type safety
- **Workers mypy 14 → 0** (#115) + **Packages mypy 129 → 0** (#117,
  #118, #125) — three trees pinned at `MAX_MYPY_ERRORS=0` (nexus-api
  was already 0). 14+ latent silent-failure bugs surfaced and fixed
  along the way: `InferenceProvider.stream` async-vs-async-generator
  signature mismatch (every streaming caller broke at type check),
  `agent.py` `call_llm` wrong-shape + missing-await + nonexistent
  `.content` (silent fallback every workflow run), 3 SDK examples
  using dict indexing on pydantic models (would crash on first run),
  `meeting_scheduler.py` loop variable shadowing an `except ValueError
  as e`, `selva_tools/approval.py` non-existent `AsyncSessionLocal`,
  calendar tools API mismatches, operations.py dead Dhanam branch,
  router pydantic ValidationError on prompt-cache hit, subgraph
  uncompiled-graph `.invoke()`, missing awaits in agent learning
  loop.
- **CI test-py + wire-types-drift gates restored** (#121) — both
  silently red on every commit for a week+. test-py needed
  `ENVIRONMENT: development` so Settings validators wouldn't reject
  dev defaults; wire-types needed regeneration after PR #114 + #116
  changed FastAPI route docstrings.
- **Workers `__main__.py` coverage 42% → 96%** (#112) — 47-test
  task lifecycle suite. Surfaced + flagged-as-xfail (later fixed in
  #113) the OSError swallow bug.

### Architecture (RFCs landed, implementation tracked)

- **RFC 0018 — A2A external-tenant model** (#136) — closes the
  synthetic `org_id="a2a-external"` smell. Migration 0029 scaffolds
  `external_a2a_callers` table; bridge cutover deferred to
  follow-up PR per RFC Phase D.
- **RFC 0019 — Cross-service CDC audit topic** (#140) — Postgres
  CDC (Debezium → Kafka → audit topic) replaces the manual
  `emit_event_db` discipline. 4-phase 10-week migration. Operator
  decisions blocking start: Kafka cluster ownership, ~$300-800/mo
  cost approval.
- **RFC 0020 — Per-tenant data residency for SAT-bound tenants**
  (#144) — hybrid Pattern A (dedicated MX-region cluster for
  SAT-bound) + Pattern C (gateway-routed shards for everyone else),
  driven by `tenant_configs.data_residency_region` ENUM. Phased
  migration. Implementation blocked on operator cluster-provisioning
  decision.
- **RFC 0021 — Multi-region failover** (#144) — active-passive
  (warm standby, ~30min RTO) for next 12 months → active-active in
  Q1 2027 once regional infrastructure matures through quarterly
  drills. Active-active multi-master rejected upfront. Implementation
  blocked on RFC 0020's cluster topology decisions.

### Compliance + ecosystem cohesion (post-#143 additions)

- **Per-period consent ledger key tracking** (#145) — closes
  the §6 limitation in `docs/SECRET_ROTATION_POLICY.md`. Migration
  0030 adds `consent_ledger_signing_keys` table (key_version PK,
  partial unique index on `is_current=true`); `consent_ledger`
  rows carry `signing_key_version` FK so old rows verify under
  their original key forever. New
  `POST /api/v1/admin/consent-ledger/promote-key` endpoint
  (admin/platform role-gated) atomically retires old + inserts
  new key + emits `consent_ledger.key_promoted` audit event.
  `scripts/rotate-secret.sh consent-ledger-signing` updated to
  call promote-key FIRST then patch K8s Secret. Quarterly
  rotation cycle now safely includes this secret. 10 new tests
  + 30 existing consent/onboarding tests still green.

### Documentation

- **Audit trail gap analysis** (#124) — 38 routers / 53 mutation
  sites / 37 gaps catalogued (now closed via waves 1-3). Per-router
  table with suggested event types. Implementation guidance, test
  pattern, 3-week phased rollout estimate, LFPDPPP + GDPR
  compliance notes. Doc supersedes itself now that all 37 sites are
  closed.
- **RLS Phase 1.5 audit** (PR #107, pre-session) — six silent-break
  sites identified; reap-stale fixed (#114), 5 break sites migrated
  to `tenant_session()` (#126), strict mode landed (#134).
- **Load test scenario + runbook** (#128) — k6 100-concurrent-tasks
  scenario + per-metric calibration → production-config mapping +
  results template + quarterly cadence.
- **Observability vendor selection** (PR #109, pre-session) —
  Grafana Cloud Free→Pro recommendation for traces+logs+metrics;
  Sentry Team plan EU region recommendation. Operator decision
  pending.
- **AUDIENCE_FILTER rollout plan** (PR #109, pre-session) — synthetic
  exercise pre-launch; 48h soak when first paying tenant onboards;
  flip env var after.
- **Secret rotation policy** (#138) — quarterly cadence, procedure,
  rollback, audit, compliance (SOC 2 CC6.1, NIST SP 800-57 Part 1,
  MX LFPDPPP). §6 limitation closed by #145 — quarterly cycle now
  safely includes consent-ledger-signing.
- **CDC audit topic RFC** (#140) — see Architecture section.
- **CHANGELOG `[2.3.0]` + CLAUDE.md operator patterns** (#143) —
  this very entry, plus the "Patterns Added in v2.3.0" reference
  section in CLAUDE.md (idempotency adoption recipe,
  `tenant_session()` usage, RLS strict mode + `admin_session()`,
  PostgresSaver lifecycle, 5-item adoption checklist).
- **Data residency RFC #0020 + multi-region failover RFC #0021**
  (#144) — see Architecture section.
- **Wrap-up doc refresh** (this PR) — ROADMAP scorecard updated to
  2.3.0 baseline with 4 dimensions newly improved (per-period
  consent ledger key tracking → consent ledger integrity 90→95%;
  Audit trail in-Selva 80→100%; Architecture RFCs landed 1→5;
  Secret rotation 0→100%). Cross-service audit correlation added as
  separate dimension at 20% (RFC 0019 shipped, awaits Kafka
  provisioning). Top-line metrics updated: 32 Alembic migrations
  (was 25), 828 test files (was 794), 5 architecture RFCs.

### Operator todo list (gating items not in this release)

- Populate `STRIPE_PRICE_TO_TIER_MAP` env var from Stripe Dashboard
- Wire `OTEL_EXPORTER_OTLP_ENDPOINT` per the vendor selection doc
- Provision Sentry per-service DSNs
- Run a synthetic AUDIENCE_FILTER exercise + flip
  `AUDIENCE_FILTER_ENABLED=true` after 24-48h shadow-block soak
- Schedule first quarterly secret rotation
- Run the load-test scenario in staging
- Run a backup/restore drill in staging
- Decide Kafka cluster ownership for CDC RFC 0019

## [2.2.0] - 2026-04-17

### Added

- **Outbound Voice Mode**: Three legal sender modes — `user_direct`,
  `dyad_selva_plus_user`, and `agent_identified` — stored on
  `tenant_configs.voice_mode` (nullable; NULL means onboarding incomplete).
- **Append-Only Consent Ledger**: `consent_ledger` table (migration 0018)
  with UPDATE/DELETE REVOKEd from the `autoswarm_app` role at the database
  level. SHA-256 signature replay verifiable via `compute_signature()`.
- **Onboarding Flow**: `/onboarding` full-page gate forces voice-mode
  selection before `/office` loads. `VoiceModeChangeModal` for later changes.
  `user_direct` requires explicit SB-1001 + CASL acknowledgement.
- **Tool Enforcement**: `SendEmailTool` and `SendMarketingEmailTool` refuse
  to send when `voice_mode` is NULL. `agent_identified` mode also verifies
  SPF/DKIM/DMARC alignment on `selva.town` (10-min TTL cache).
- **Compliance Research**: Clauses versioned `voice-mode-v1.0`. Coverage:
  Mexico LFPDPPP 2025, GDPR Art.7, CAN-SPAM, California BOT Act SB-1001,
  CASL Canada, LGPD Brazil.

## [2.1.1] - 2026-04-16

### Fixed

- **Dispatch Dedup**: `HeartbeatService` tracks recently dispatched lead IDs
  in a 24h-TTL map. Same lead cannot be dispatched twice in 24 hours.
- **Dispatch Cap**: `MAX_DISPATCHES_PER_TICK = 10` prevents cost explosion
  when CRM has many hot leads.
- **Payload Sanitisation**: Auto-dispatch uses explicit field pick instead of
  spread, closing playbook injection vector.
- **HITL Re-enabled**: Auto-dispatched CRM tasks now require approval with
  $50/day financial cap (was unbounded).
- **PII Scrubbed**: Task descriptions use `lead:<id>` not contact names; emails
  masked in logs.
- **Sender Lockdown**: `from_address` parameter removed from `SendEmailTool`.
  All emails use `EMAIL_FROM` env var — no agent-controlled sender forgery.
- **Events Auth**: `POST /api/v1/events` now requires Bearer auth.
- **Proxy Limits**: `max_tokens` capped at 32768; embedding input capped at
  256 items per request.

## [2.0.0] - 2026-04-15

### Added

- **Enterprise Mexican Market** (Sprints 1-7): KarafielAdapter (compliance),
  DhanamAdapter (billing + economic data), TezcaAdapter (legal), CrawlerAdapter
  (scraping).
- **Tools + Graphs**: 74 tools, 12 graphs (billing, accounting, sales,
  intelligence). 15 es-MX locale skills.
- **TenantConfig**: RFC validation, multi-tenant provisioning with 6 Mexican
  departments, daily task limits.

## [1.2.1] - 2026-04-14

### Fixed

- **Hub Client Test**: `test_hub_client.py` now uses `MagicMock` for httpx
  responses (sync) and `AsyncMock` only for the `get()` method.
- **selvatown.com Redirect**: 301 permanent redirect from `selvatown.com`
  (and `*.selvatown.com`) to `selva.town` preserving path and query string.

## [1.2.0] - 2026-04-14

### Added

- **Solarpunk Companions**: 5 companion sprites redrawn (cat with flower
  collar, dog with leaf bandana, bio-robot with moss patches, plant dragon
  with leaf wings, tropical parrot with solar feathers).
- **Solarpunk Emotes**: 9 emotes redrawn with solarpunk theme (leaf wave,
  sun thumbsup, flower heart, sunshine laugh, sprout think, leaf clap,
  solar fire, bioluminescent sparkle, herbal tea cup).
- **Animated Tiles**: 3 animated tile types (water shimmer, candle flame,
  grow-light pulse) with 4-frame cycles at 200ms intervals.
- **Agent Idle Animations**: 3 idle sub-states (breathing, look-around,
  stretch) cycling every 5s. Working head-bob, waiting-approval sway, error
  alpha reduction + red tint.

## [1.1.0] - 2026-04-14

### Added

- **Living Office Map**: Complete map generator rewrite. 4 department biomes
  (Tech Greenhouse, Library Garden, Market Garden, Zen Garden) radiating from
  a central atrium garden. Glass corridors, blueprint gazebo, 4 review
  stations, 2 dispatch stations, 3 spawn points.
- **Atmospheric Lighting**: Department ambient tints via ADD-blended overlays.
  5 skylight golden light pools with pulsing alpha + solar sparkle particles.
- **Solarpunk Agent Halos**: idle=moss green, working=solar gold, paused=wood
  tone, error=deep red.

## [1.0.0] - 2026-04-14

### Added

- **Solarpunk Palette**: Environment tokens overhauled to warm earth tones
  (wood, bamboo, moss). New "solarpunk" preset with tech-garden, market-garden,
  zen-garden, library-garden department biomes.
- **4-Direction Walk Cycles**: 12-pose avatar system (4 dirs × 3 frames).
  `AvatarCompositor` generates 384x32 spritesheets. FF6-style JRPG 1-2-1-3
  walk pattern at 8fps.
- **Solarpunk UI Tokens**: 17 Tailwind colors (wood, bamboo, moss, leaf, solar,
  sky, earth, glass, bloom, glow, sand). New CSS classes for panels, buttons,
  borders.
- **Particle Overhaul**: 6 new particle textures (leaf, petal, firefly, spore,
  sparkle, glint). Ambient dust replaced with floating leaves + fireflies.

## [0.9.0] - 2026-04-14

### Added

- **Mobile UX Polish**: Haptic feedback (`navigator.vibrate(50)`) on touch
  action buttons. Compact layout for screens <640px. `MobileNav` bottom tab
  bar visible only on touch devices. CSS safe area padding for notched phones.
- **Competitive Benchmark**: `docs/BENCHMARK.md` — feature matrices vs Hermes
  Agent, OpenClaw, Gather, WorkAdventure, CrewAI, LangGraph, MS Agent
  Framework. Platform stats, security posture, parity scorecard.

## [0.8.0] - 2026-04-14

### Added

- **Tool Expansion (40→54)**: 14 new tools across 5 categories: Email
  (SendEmail via Resend, ReadEmail), Calendar (Create/List), Database
  (SQLQuery, SQLWrite, DatabaseSchema), HTTP (HTTPRequest with SSRF
  protection, GraphQL, Webhook with HMAC), Documents (GeneratePDF, ParsePDF,
  MarkdownToHTML, GenerateChart).
- **A2A Protocol**: Agent-to-Agent interop package. AgentCard discovery via
  `.well-known/agent.json`, task exchange, SSE streaming. `A2AClient` for
  calling external agents and `CallExternalAgentTool` registered.

## [0.7.0] - 2026-04-14

### Added

- **Voice Mode (STT)**: `SpeechToTextTool` with OpenAI Whisper API
  integration. Voice API endpoints `POST /voice/transcribe` and
  `POST /voice/dispatch`. Meeting graph `transcribe()` node tries STT tool
  first, falls back to LLM.
- **LiveKit SFU Scaling**: Hybrid P2P/SFU proximity video. When player count
  exceeds `LIVEKIT_THRESHOLD`, server sends `mode: "sfu"` and LiveKit
  credentials on join. Client auto-switches from simple-peer to LiveKit
  Room with proximity-based track subscription.

## [0.6.0] - 2026-04-14

### Added

- **Screen Sharing Polish**: Quality presets (`auto`/`720p`/`1080p`) via
  `getDisplayMedia` constraints. System audio capture mixing system + mic
  tracks. Quality dropdown in `MediaControls.tsx`.
- **Iterative Skill Refinement**: `SkillRefiner._llm_refine()` loops up to
  `max_iterations=3` — refine via LLM, validate in sandbox, retry with
  error context. `RefinerMetrics` exposed via `GET /skills/refiner/metrics`.
- **PWA Support**: `manifest.json`, minimal service worker (cache shell,
  network-first, skip API/WS), `ServiceWorkerRegistrar` client component,
  PWA icons. Mobile "Add to Home Screen" now works.

## [0.5.2] - 2026-04-14

### Fixed

- **Skills Package**: Resolved dual-path collision — `pyproject.toml`
  `where=["src"]` was hiding the real `autoswarm_skills/` root package.
- **Worker Settings**: Added missing `environment` field that was crashing
  validator with AttributeError on every instantiation.
- **Colyseus State Sync**: Moved megaphone and spotlight from module-level
  variables to `OfficeStateSchema` fields, eliminating cross-room race
  conditions.
- **Player-Not-Found Errors**: 9 Colyseus handler locations now send error
  messages instead of silently returning.
- **Dashboard Accessibility**: Added `aria-live="polite"` to MetricsDashboard
  stats container and DashboardPanel kanban area.

## [0.5.1] - 2026-04-14

### Fixed

- **K8s workers.yaml**: Fixed duplicate `env:` key that silently dropped
  `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY` and 3 other env vars.
- **Alembic Migration Chain**: Orphaned `0004_wave2_tables.py` renamed to
  `0014_wave2_tables.py` and chained after migration 0013.
- **Gateway SSRF Protection**: `_validate_webhook_url()` blocks private IP
  ranges, enforces http/https scheme, applied to all 17 webhook handlers.
- **Bare Exception Logging**: 16 silent `except Exception: pass` blocks across
  nexus-api routers and worker graphs now log with `exc_info=True`.
- **Docker Dev Parity**: Dev compose now uses `pgvector/pgvector:pg16` for
  production parity. Added coturn service for WebRTC TURN in development.

## [0.5.0] - 2026-04-14

### Added

- **Landing Page** (`/`): Server-rendered marketing page (hero, feature grid,
  how-it-works, footer). No auth, no game deps.
- **Demo Mode** (`/demo`): Sandboxed office with 8 simulated agents. Client
  generates unsigned JWT with `org_id: "demo-public"`. Colyseus filterBy
  isolates demo rooms.
- **DemoSimulator**: Cycles agents through idle → working → waiting_approval
  → idle every 12-15s. Auto-approves after 15s if no human action.
- **Route Restructure**: `/` → landing, `/office` → protected office (was
  `/`), `/demo` → public demo. Login default redirect changed to `/office`.

## [0.4.0] - 2026-03-16

### Added

- **Experience Recording**: Task outcomes stored in `ExperienceStore` (per-role,
  30-day temporal decay) and `MemoryStore` (per-agent). Score mapping:
  completed=1.0, denied=0.2, failed=0.0.
- **Reflexion**: LLM self-critique on failures (Reflexion NeurIPS 2023 pattern).
  Falls back to basic text when LLM unavailable.
- **Experience Injection**: Plan/implement/review prompts now include similar
  past experiences and agent memories.
- **Agent Performance Tracking**: 6 columns on `Agent` model
  (`tasks_completed`, `tasks_failed`, `approval_success_count`,
  `approval_denial_count`, `avg_task_duration_seconds`, `last_task_at`).
  `PATCH /agents/{id}/stats` accepts delta increments. Migration 0013.
- **Performance-Aware Dispatch**: Skill-based agent matching weighted by
  performance (30% performance, 70% skill overlap). New agents default to
  neutral 0.5.

## [0.3.1] - 2026-03-15

### Fixed

- **`test()` Node**: Uses shared `_run_async()` instead of
  `asyncio.get_event_loop()`, which crashed in ThreadPoolExecutor threads.
  `run_async()` consolidated into `graphs/base.py` (no duplicate
  implementations).
- **Worker Auth Hardening**: `WORKER_API_TOKEN` env var (default `dev-bypass`).
  `auth.py:get_worker_auth_headers()` centralizes all worker-to-API auth.
- **Org Config Bootstrap**: `make setup-org-config` copies template to
  `~/.autoswarm/org-config.yaml`. Wired into `make dev-full`.
- **Enhanced System Prompts**: `prompts.py` provides repo-context-aware plan/
  implement/review prompts with strict JSON format instructions.
- **Docker Compose Compat**: `DOCKER_COMPOSE` Makefile variable auto-detects
  `docker-compose` (v1) vs `docker compose` (v2 plugin).

## [0.3.0] - 2026-03-15

### Added

- **Worker Concurrency**: `MAX_CONCURRENT_TASKS` env var (default 3).
  Semaphore-bounded `asyncio.create_task()` with graceful shutdown drain.
- **LLM JSON Retry**: `implement()` retries LLM up to 2 times on
  `JSONDecodeError`, re-prompting with error context.
- **Git Credential Isolation**: Token passed via subprocess env instead of
  `os.environ`.
- **Dispatch Rate Limiting**: Per-user sliding window via `MessageRateLimiter`
  on `POST /dispatch` (default 10 req/60s).
- **Inference Retry + Fallback**: `ModelRouter.complete()` retries primary
  once, then falls through to alternative providers.
- **Approval Audit Trail**: `responded_by` column on `approval_requests`
  (migration 0012). Populated from JWT `sub` claim.

## [0.2.0] - 2026-03-15

### Added

- **Guest Access**: Dedicated `/guest` join page with invite links, JWT-based
  guest tokens (via Janua), and per-endpoint permission gating (guests can
  observe but cannot dispatch tasks, approve/deny, or edit workflows).
- **Security Headers**: Content-Security-Policy header with configurable
  `csp_extra_sources`. Fixed `Permissions-Policy` to allow WebRTC camera and
  microphone for the app's own origin.
- **WebSocket Rate Limiting**: Sliding-window rate limiter for nexus-api WS
  endpoints and per-client message throttling in Colyseus (exempt: `move`,
  `webrtc_signal`).
- **Fire-and-Forget Retry**: Shared `http_retry.py` utility with exponential
  backoff (0.5s → 1s → 2s) and per-host circuit breaker (5 failures → 30s
  cooldown). Used by `task_status.py` and `event_emitter.py`.
- **Database Pool Tuning**: Configurable `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
  `DB_POOL_RECYCLE`, `DB_POOL_TIMEOUT` env vars. New `/api/v1/health/pool-stats`
  endpoint.
- **Environment Variable Validation**: Pydantic `@model_validator` on both
  nexus-api and worker `Settings`. Warns on insecure defaults in non-dev
  environments, validates URL formats at startup.
- **OpenTelemetry Foundation**: Optional tracing via `OTEL_EXPORTER_OTLP_ENDPOINT`
  env var. No-op when unset. W3C Trace Context propagation in request-id
  middleware. OTel spans on Redis pool operations.
- **Playwright E2E Tests**: Foundation test suite (login, task dispatch,
  approval flow) with shared fixtures for dev-auth-bypass login.
- **Admin Dashboard Tests**: vitest + @testing-library/react test suites for
  all 8 admin pages.
- **KEDA Queue Scaling Docs**: Guide and example `ScaledObject` manifest for
  Redis Stream-based worker autoscaling.
- **CHANGELOG**: Retroactive changelog in Keep a Changelog format.

### Changed

- Colyseus `onAuth` hook verifies JWT via Janua JWKS (dev bypass preserved).
  Room isolation per `orgId` via `filterBy`.
- `useUserPermissions` hook derives UI permission flags from JWT claims.
  Components hide/disable controls for guests.
- Database engine creation moved to `@lru_cache` `get_engine()` for
  configurable pool parameters.

### Removed

- Legacy Redis LIST dual-write (`LPUSH autoswarm:tasks`). Workers consume
  exclusively from Redis Streams. See `docs/MIGRATION_LEGACY_QUEUE.md`.
- `legacy_queue_depth` field from `/api/v1/health/queue-stats`.

### Fixed

- `Permissions-Policy: camera=(), microphone=()` blocked WebRTC video/audio
  on the app's own origin.
- Fire-and-forget HTTP calls in `task_status.py` and `event_emitter.py` now
  retry on failure instead of silently dropping updates.

## [0.1.0] - 2026-03-14

### Added

- Full-stack AI agent orchestration platform with gamified virtual office.
- 13 AI agents across 4 departments (Engineering, Research, CRM, Support).
- 6 LangGraph execution graphs (coding, research, CRM, deployment, puppeteer,
  meeting) plus custom YAML workflows.
- Visual Workflow Builder (React Flow) with 8 node types and conditional edges.
- Proximity-based WebRTC video/audio with locked bubbles and noise suppression.
- Avatar customization, emotes, companions, and player status.
- Interactive Tiled map with 10 interactable types, click-to-move pathfinding,
  and multi-room navigation.
- Skill Marketplace for community skill discovery and installation.
- Python SDK with CLI (`autoswarm dispatch/agents/tasks`).
- Full-stack observability: TaskEvent stream, OpsFeed, MetricsDashboard.
- MADFAM Intelligence Architecture: org-config-driven model routing, task-type
  assignments, Thompson Sampling orchestration.
- Production infrastructure: Redis Streams task queue, connection pooling with
  circuit breaker, Prometheus metrics, Sentry integration, K8s PDB/HPA/NetworkPolicy.
- Calendar integration (Google + Microsoft), AI meeting notes, chat persistence.
- Mobile support with virtual joystick and touch action buttons.
- Simplified accessible HTML-only view alternative.
- 660+ TypeScript tests, 700+ Python tests, 160+ worker tests.
