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
pnpm test             # TypeScript tests (182 tests across 14 suites)
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

### Interactive Map Objects

- `InteractableManager` (`apps/office-ui/src/game/InteractableManager.ts`) parses
  the `interactables` Tiled object layer and creates Phaser zones with overlap
  detection. Each object has an `interactType` property: `url`, `popup`,
  `jitsi-zone`, or `silent-zone`.
- When the player overlaps an interactable zone, a `[E] label` prompt appears.
  Pressing E (buttonX) triggers the action.
- `url` and `jitsi-zone` types emit `open_cowebsite` → `CoWebsitePanel.tsx`
  renders a sliding iframe panel from the right (50vw max 640px, sandboxed).
- `popup` type emits `show_popup` → `PopupOverlay.tsx` renders a centered modal.
- `silent-zone` emits `silent_zone_enter`/`silent_zone_exit` events for
  muting proximity audio (Feature 4).

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

## Sprite Assets

- Pre-generated pixel-art PNGs live in `apps/office-ui/public/assets/` (sprites,
  tilesets, UI icons). These are committed to the repo.
- Regenerate with `make generate-assets` (runs `scripts/generate-assets.js` using
  `@napi-rs/canvas`).
- `BootScene.ts` loads sprite files with automatic canvas-rectangle fallback if any
  PNG fails to load. Department zone overlays are always canvas-generated. The emote
  spritesheet (`emotes.png`, 9 frames at 32x32) is also loaded here.
- `OfficeScene.ts` plays walk animations for the Tactician (4 dirs x 3 frames) and
  idle/working animations for agents.
