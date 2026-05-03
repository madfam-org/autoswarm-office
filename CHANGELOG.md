# Changelog

All notable changes to **Selva Office** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
