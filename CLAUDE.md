# CLAUDE.md -- AutoSwarm Office

## Critical Paths

- `apps/nexus-api/src/main.py` -- FastAPI application entry point
- `apps/office-ui/src/app/page.tsx` -- Office UI root page
- `packages/orchestrator/src/orchestrator.py` -- Swarm orchestration engine
- `packages/permissions/src/matrix.py` -- HITL permission matrix
- `packages/permissions/src/engine.py` -- Permission evaluation engine
- `packages/inference/src/router.py` -- LLM model routing logic

## Port Assignments

| Port | Service | Notes |
|------|---------|-------|
| 4300 | nexus-api | Central API |
| 4301 | office-ui | Next.js frontend |
| 4302 | admin | Admin dashboard |
| 4303 | colyseus | Game state server |

These ports do not conflict with Janua (4100-4104) or Enclii (4200-4204).

## Commands

```bash
make dev              # Start all services (TS + Python)
make test             # Run all tests
make lint             # Run all linters
make typecheck        # TypeScript + mypy
make build            # Build all packages
make docker-dev       # Start Postgres + Redis
make db-migrate       # Run Alembic migrations
make db-seed          # Seed departments and agents
make generate-assets  # Regenerate pixel-art sprite PNGs

pnpm dev              # TypeScript services only
pnpm build            # Build TypeScript packages
pnpm lint             # ESLint
pnpm test             # TypeScript tests (250 tests across 22 suites)
pnpm typecheck        # TypeScript type checking

uv run pytest         # Python tests (238 tests)
uv run ruff check .   # Python linting
uv run mypy .         # Python type checking
```

## MADFAM Ecosystem

- **Janua** handles all authentication. Never implement custom auth. Use the
  `get_current_user` dependency in FastAPI and the Next.js middleware for session
  validation. Janua tokens are JWTs with `sub`, `email`, `roles`, and `org_id` claims.

- **Dhanam** handles billing and subscriptions. Compute token budgets are enforced
  by the orchestrator package and tracked in the `compute_token_ledger` table.
  Use the billing router at `apps/nexus-api/src/routers/billing.py`.

- **Enclii** handles deployment. The `.enclii.yml` defines all three services.
  The `deploy-enclii.yml` GitHub Actions workflow builds images and notifies Enclii.

- Read sibling repo `llms-full.txt` files for full API surfaces of Janua, Dhanam,
  and Enclii.

## Coding Standards

### Python
- **Linter**: ruff (target py312, line-length 100)
- **Type checker**: mypy (strict mode)
- **Models**: pydantic for all request/response schemas
- **ORM**: SQLAlchemy with async sessions
- **Tests**: pytest with pytest-asyncio
- **Imports**: isort via ruff, `autoswarm` as known-first-party

### TypeScript
- **Strict mode**: enabled in all tsconfig.json files
- **Linter**: ESLint with shared config from `packages/config/eslint`
- **Formatter**: Prettier
- **Tests**: vitest with jsdom + @testing-library/react for UI components
- **Build**: Turborepo for monorepo orchestration
- **Package manager**: pnpm with workspace protocol

## Git Workflow

- Feature branches only -- never commit directly to `main`.
- Conventional commits enforced by commitlint:
  `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`
- PRs require CI to pass before merge.

## Skills System

The `packages/skills/` package implements the AgentSkills standard.

- **Core skills** (11) live in `packages/skills/skill-definitions/`. Always loaded.
- **Community skills** (~25) live in `packages/skills/community-skills/`. Vendored from
  [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills).
  Disabled by default.
- `SkillTier` enum: `CORE` | `COMMUNITY`. Set by the registry during discovery, not
  from YAML frontmatter.
- Enable community skills via:
  - Env var: `AUTOSWARM_COMMUNITY_SKILLS_ENABLED=true`
  - Runtime: `get_skill_registry().enable_community_skills()`
  - REST API: `POST /api/v1/skills/community/enable`
- Core skills always take precedence on name collision with community skills.
- Community skill scripts under `community-skills/` are excluded from ruff linting
  via `extend-exclude` in `pyproject.toml`.

## Architecture Notes

- The Redis queue key is `autoswarm:tasks` (LPUSH to enqueue, BRPOP to dequeue).
- WebSocket approval events use the `ConnectionManager` singleton in
  `apps/nexus-api/src/ws.py`.
- LangGraph `interrupt()` is used to pause agent execution for HITL approval.
- Synergy bonuses stack multiplicatively (see `packages/orchestrator/src/synergy.py`).
  Synergy rules support both role-based (`required_roles`) and skill-based
  (`required_skills`) requirements.
- `SwarmOrchestrator.match_agents_by_skills()` selects idle agents by skill overlap
  score. The swarms router auto-selects agents when `required_skills` is provided
  without explicit `assigned_agent_ids`.
- Agents have `skill_ids` (JSON column) and `effective_skills` (computed from
  `skill_ids` or `DEFAULT_ROLE_SKILLS` fallback). Skills flow from DB → API →
  Colyseus schema → Phaser UI badges.
- The gateway `HeartbeatService` scrapes GitHub events and dispatches enemy waves
  via WebSocket to the approvals endpoint, which converts them into `SwarmTask`
  records enqueued on Redis.
- Worker graph nodes (`plan`, `implement`, `review`) use `call_llm()` from
  `autoswarm_workers.inference` with a `ModelRouter` that auto-discovers providers
  from env vars. Graphs fall back to static logic when no LLM is configured.
- The permission matrix is evaluated by `packages/permissions/src/engine.py` before
  every tool invocation in the worker.

### Multi-Player & Chat

- The Colyseus `OfficeStateSchema` uses `players: MapSchema<TacticianSchema>`
  (keyed by `client.sessionId`) instead of a single tactician. Each player has
  `sessionId`, `name`, `x`, `y`, `direction`.
- `OfficeRoom.onJoin()` creates a player entry; `onLeave()` removes it. System
  messages are broadcast to `chatMessages` on join/leave/approval events.
- `handleMovement` looks up the moving player via `state.players.get(client.sessionId)`
  so multiple players move independently.
- `chatMessages: ArraySchema<ChatMessageSchema>` holds the last 50 messages
  (user + system). The `chat` message handler validates content length (max 500).
- Office world bounds are 1280x704 (40x22 tiles at 32px).
- `OfficeScene` renders remote players as interpolated sprites with name labels.
  Local player movement is broadcast via `GameEventBus` at ~15fps with a 1px
  dead-zone to avoid flooding.
- `ChatPanel` is a collapsible React overlay (bottom-left). `T`/`/` to focus,
  `Esc` to unfocus. `GamepadManager.chatFocused` suppresses keyboard game input
  while typing.

### Tiled Map Support

- `BootScene` loads `office-default.tmj` (Tiled JSON) and an `office-tiles` image.
  `OfficeScene.create()` calls `loadTiledMap()`; on failure it falls back to the
  procedural floor + department-zone rendering that existed before.
- `TiledMapLoader.ts` parses department zones, review stations, and spawn points
  from Tiled object layers. Collision is set on an invisible `collision` layer via
  `setCollisionByExclusion([-1])`.
- The default map lives at `apps/office-ui/public/assets/maps/office-default.tmj`.

### Emotes & Reactions

- Emotes are **ephemeral** — not persisted in the Colyseus schema. The client sends
  an `emote` message with `{ type }` (one of 9 whitelisted types in
  `apps/colyseus/src/handlers/emotes.ts`). The server validates and broadcasts
  `player_emote` to all clients.
- The client renders a speech-bubble sprite above the player with a 3-second
  scale-up + fade-out tween (`OfficeScene.showEmoteBubble()`). Falls back to
  Unicode emoji text if the emotes spritesheet fails to load.
- `EmotePicker.tsx` provides a 3x3 grid UI toggled with `R`, quick-select `1-9`.
- `GamepadManager.emotePickerFocused` suppresses keyboard movement while the
  picker is open.

### Avatar Customization

- `AvatarConfig` (in `packages/shared-types/src/avatar.ts`) defines 5 properties:
  `skinTone`, `hairStyle`, `hairColor`, `outfitColor`, `accessory`.
- Config is persisted in `localStorage` via `useAvatarConfig` hook, and sent to
  the server via `avatar` message → stored as JSON string on
  `TacticianSchema.avatarConfig`.
- `AvatarCompositor.ts` generates a composite 32x32 canvas texture at runtime,
  keyed by config hash for caching. No pre-generated avatar spritesheets needed.
- `AvatarEditor.tsx` is a full-screen modal shown on first visit. Users can
  re-open it via the "Avatar" button in the top-right.
- Remote players' avatar textures are applied during `reconcileRemotePlayers()`
  based on their `avatarConfig` schema field.

### Proximity Video/Audio (WebRTC)

- **Server-side**: `proximity.ts` runs a 5Hz loop calculating which players are
  within 200px. It sends `proximity_players` messages to each client listing
  nearby session IDs. `signaling.ts` relays `webrtc_signal` messages between
  clients (SDP offers/answers, ICE candidates) — pure pass-through.
- **Client-side**: `useProximityVideo` hook manages peer connections using
  `simple-peer` (25KB). On receiving `proximity_players`, the client with the
  lexicographically lower sessionId initiates offers (deterministic, no races).
  Max 6 peers per group.
- **UI**: `VideoOverlay.tsx` renders 64px circular `<video>` bubbles (React DOM
  over Phaser canvas). `MediaControls.tsx` provides M (mute) and V (camera)
  toggle buttons.
- **STUN**: Google free STUN servers for dev. Add coturn for production.
- **Dependency**: `simple-peer@^9.11.1`, `@types/simple-peer@^9.11.8`.

### Interactive Map Objects

- `InteractableManager` (`apps/office-ui/src/game/InteractableManager.ts`) parses
  the `interactables` Tiled object layer and creates Phaser zones with overlap
  detection. Each object has an `interactType` property: `url`, `popup`,
  `jitsi-zone`, `silent-zone`, or `dispatch`.
- When the player overlaps an interactable zone, a `[E] label` prompt appears.
  Pressing E (buttonX) triggers the action.
- `url` and `jitsi-zone` types emit `open_cowebsite` → `CoWebsitePanel.tsx`
  renders a sliding iframe panel from the right (50vw max 640px, sandboxed).
- `popup` type emits `show_popup` → `PopupOverlay.tsx` renders a centered modal.
- `silent-zone` emits `silent_zone_enter`/`silent_zone_exit` events for
  muting proximity audio (Feature 4).
- `dispatch` type emits `open_dispatch` → `TaskDispatchPanel.tsx` renders a
  sliding form panel for dispatching swarm tasks.

### Mobile Support

- `VirtualJoystick` (`apps/office-ui/src/game/VirtualJoystick.ts`) renders at
  bottom-left: 80px base + 32px thumb, pointer drag with 0.2 deadzone.
  Only responds to left-half screen touches.
- `TouchActionButtons` (`apps/office-ui/src/game/TouchActionButtons.ts`) renders
  4 circular buttons at bottom-right: Approve (green), Deny (red), Inspect (cyan),
  Emote (yellow).
- `useTouchDetection` hook detects touch capability and orientation.
- OfficeScene applies 1.5x camera zoom on touch devices for better visibility.
- Joystick input merges with gamepad/keyboard in the update loop.

### Task Dispatch UI

- `useTaskDispatch` hook (`apps/office-ui/src/hooks/useTaskDispatch.ts`) POSTs to
  `POST /api/v1/swarms/dispatch`. State machine: idle → submitting → success | error.
- `TaskDispatchPanel` (`apps/office-ui/src/components/TaskDispatchPanel.tsx`) is a
  sliding panel (right side, w-80) with description, graph type selector, optional
  agent assignment, and optional skill requirements.
- Entry points: (1) walk to a dispatch station on the map → press E, (2) click
  "+ New Task" button in the DashboardPanel header.
- Dispatch stations are `interactables` objects in `office-default.tmj` with
  `interactType: "dispatch"` at (304,296) and (544,296) in the central corridor.
- Mutual exclusion: opening dispatch panel closes the dashboard panel.
- Uses `chat-focus` gameEventBus event to suppress keyboard game input while typing.

### Map Scripting API (Feature 9)

- `ScriptBridge` (`apps/office-ui/src/game/scripting/ScriptBridge.ts`) manages
  hidden sandboxed iframes for map scripts. Scripts defined via `scriptUrl`
  property on the Tiled map. Communication via `postMessage` with command whitelist.
- `ScriptAPI` (`apps/office-ui/src/game/scripting/ScriptAPI.ts`) defines the
  `AS.*` namespace injected into script iframes: `AS.chat.sendMessage()`,
  `AS.camera.moveTo()`, `AS.player.moveTo()`, `AS.ui.openPopup()`,
  `AS.ui.openCoWebsite()`, `AS.onPlayerEntersArea()`, `AS.onPlayerLeavesArea()`.
- `InteractableManager` emits `zone_enter`/`zone_leave` events on the gameEventBus;
  `OfficeScene` forwards these to `ScriptBridge.notifyAreaEvent()`.
- Lifecycle: created on map load if `scriptUrl` property exists, destroyed on
  scene shutdown.

### UI/UX Infrastructure

- **ErrorBoundary** (`apps/office-ui/src/components/ErrorBoundary.tsx`) wraps the
  main page content. Class component with fallback UI + retry button.
- **Toast system**: `ToastProvider` wraps the app in `page.tsx`. Use
  `useToast().addToast(message, severity)` from any component. Toasts auto-dismiss
  after 5s with a 200ms exit animation (`animate-slide-out-right`). Toasts have a
  `dismissing` flag for exit animation state. Severity: `success`, `error`,
  `warning`, `info`.
- **Focus trapping**: `useFocusTrap(active)` hook returns a ref. Applied to
  `AvatarEditor`, `PopupOverlay`, `TaskDispatchPanel`. Traps Tab cycling and
  restores previous focus on close.
- **Loading screen**: `BootScene.preload()` renders a progress bar with percentage
  during asset loading. Loading text pulses (alpha 0.7→1). Rotating tips cycle
  below the bar every 2.5s ("Walk near agents to interact...", etc.).
- **Help overlay**: Press `?` to toggle. Has backdrop, `[X]` close button, and
  gamepad mappings alongside keyboard shortcuts.
- **Design system tokens** in `tailwind.config.ts`:
  - Semantic colors: `semantic-success`, `semantic-error`, `semantic-warning`,
    `semantic-info`
  - Z-index scale: `z-hud` (20), `z-video` (30), `z-backdrop` (40),
    `z-modal` (50), `z-toast` (60)
  - Typography: `text-retro-xs` (7px), `text-retro-sm` (8px),
    `text-retro-base` (10px), `text-retro-lg` (12px)
  - Button `xs` size variant in `packages/ui/src/button.tsx`
- **Font loading**: Press Start 2P loaded via `next/font/google` in `layout.tsx`
  (CSS variable `--font-pixel`). No HTTP `@import` in globals.css.
- **iframe sandbox**: `CoWebsitePanel` uses `allow-scripts allow-forms allow-popups`
  (no `allow-same-origin`).
- **Global focus indicators**: `*:focus-visible` outline set in `globals.css`.
- **Responsive panels**: `ChatPanel`, `DashboardPanel`, `TaskDispatchPanel` use
  `w-full max-w-80 sm:w-80` for mobile.
- **Responsive game fonts**: `responsiveFontSize(base)` in `OfficeScene.ts` scales
  with viewport width.
- **Touch feedback**: VirtualJoystick thumb alpha (0.4 idle/0.9 active),
  TouchActionButtons scale+alpha on press, 48px min touch targets.
- **CSS animation vocabulary** in `globals.css` (`@layer utilities`):
  - `animate-slide-in-right` / `animate-slide-out-right` (300ms/200ms)
  - `animate-fade-in` / `animate-fade-in-up` (200ms/250ms)
  - `animate-pop-in` with spring overshoot (300ms cubic-bezier)
  - `animate-pulse-border` for glowing borders (2s infinite)
- **`.retro-btn` class** in `globals.css`: hover=translateY(-1px)+glow,
  active=translateY(1px)+inset shadow. Applied to dashboard toggle, avatar
  button, chat toggle, emote button, and avatar editor action buttons.
- **`.retro-panel:hover` glow**: subtle indigo box-shadow expansion on hover.
- **CRT scanline overlay**: `.scanline-overlay::after` in `globals.css` with
  `repeating-linear-gradient` at 3% opacity. Applied to `<main>` in `page.tsx`.
- **Phaser post-FX**: CRT vignette on main camera, gated behind
  `ENABLE_POST_FX` constant in `OfficeScene.ts`.
- **Particle system**: Ambient dust motes (1 per 800ms, ADD blend, alpha
  0→0.3), tactician walk dust trail, agent status particles (cyan sparkles
  for working, red wisps for error). All gated behind `ENABLE_PARTICLES`.
  Runtime-generated 2x2 (`particle-dot`) and 3x3 (`particle-dust`) textures
  in `BootScene.ts`.
- **Department zone ambient pulse**: alpha-breathing tween (0.2→0.35) on zone
  overlays, staggered by index.
- **Agent status halos**: colored circle beneath each agent (slate=idle,
  cyan=working, amber+pulse=waiting_approval, red=error). Stored in
  `AgentSprite.statusHalo`.
- **Agent idle breathing**: subtle scaleY tween (1.0→1.04, 2s) on idle agents.
  Paused when status changes away from idle.
- **Agent name label backgrounds**: black rectangle at 0.5 alpha behind name
  text for readability over zone colors.
- **Review station glow**: pulsing alpha tween + `preFX.addGlow()` when
  `pendingApprovals > 0`. Cleared when 0.
- **Tactician spawn-in effect**: scale 0.5→1.0 + alpha 0→1 with Back.easeOut,
  indigo particle burst (8 particles).
- **Chat bubbles**: local messages right-aligned (`bg-indigo-900/50`), remote
  left-aligned (`bg-slate-800/60`), system centered italic. Staggered
  `animate-fade-in-up`.
- **Dashboard enhancements**: backdrop overlay when open (click-to-close),
  kanban cards with left-border color by status + hover translate, department
  stat bars (cyan agents bar, amber tasks bar), staggered fade-in.
- **HUD count animation**: agent count and approval count wrapped in
  `<span key={count}>` with `animate-pop-in` (re-mounts on value change).
  Approval badge gets `animate-pulse` + `animate-pulse-border` when count > 0.
- **Functional minimap**: `Minimap` sub-component in `HUD.tsx` renders to
  128x96 `<canvas>`. Draws department zones as colored rectangles, agents as
  2px role-colored dots, player as 3px indigo dot with glow ring. Fed by
  `playerPosition` state from `page.tsx` (updated on `handlePlayerMove`).
- **Avatar editor canvas preview**: real 32x32 composited avatar drawn at 4x
  scale (128x128) using pure-canvas `drawAvatar()` utility extracted from
  `AvatarCompositor.ts` logic. Updates on every config change.
  `imageSmoothingEnabled = false` + CSS `image-rendering: pixelated`.
  Modal uses `retro-panel pixel-border-accent` with `animate-pop-in`.
- **Color swatch feedback**: `active:scale-90`, selected swatches get
  `ring-2 ring-indigo-400 ring-offset-2 ring-offset-slate-900`.
- **EmotePicker pop-in**: outer container `animate-pop-in`, each button
  staggered `animate-fade-in-up` (30ms), `hover:scale-110 active:scale-95`.
- **Video overlay animations**: peer bubbles `animate-pop-in` on connect.

## Sprite Assets

- Pre-generated pixel-art PNGs live in `apps/office-ui/public/assets/` (sprites,
  tilesets, UI icons). These are committed to the repo.
- Regenerate with `make generate-assets` (runs `scripts/generate-assets.js` using
  `@napi-rs/canvas`).
- `BootScene.ts` loads sprite files with automatic canvas-rectangle fallback if any
  PNG fails to load. Department zone overlays are always canvas-generated. The emote
  spritesheet (`emotes.png`, 9 frames at 32x32) is also loaded here. Particle
  textures (`particle-dot` 2x2, `particle-dust` 3x3) are runtime-generated.
- `OfficeScene.ts` plays walk animations for the Tactician (4 dirs x 3 frames) and
  idle/working animations for agents. Post-FX, particles, and ambient effects are
  gated behind `ENABLE_POST_FX` and `ENABLE_PARTICLES` constants.
