/**
 * Centralized game constants.
 *
 * All simple numeric/string magic numbers used across the game layer live here
 * so every module references a single source of truth.
 */

import {
  TILE_SIZE_PX,
  WORLD_COLS as SHARED_WORLD_COLS,
  WORLD_ROWS as SHARED_WORLD_ROWS,
} from '@autoswarm/shared-types';

// === Layout ===
// World dimensions are owned by packages/shared-types/src/world.ts (the
// canonical source). The local re-exports below keep existing import paths
// (`./constants`) working for game-layer modules; do not redefine the
// numeric literals here.
/** @deprecated Re-exported from `@autoswarm/shared-types` (see world.ts). */
export const TILE_SIZE = TILE_SIZE_PX;
/** @deprecated Re-exported from `@autoswarm/shared-types` (see world.ts). */
export const WORLD_COLS = SHARED_WORLD_COLS;
/** @deprecated Re-exported from `@autoswarm/shared-types` (see world.ts). */
export const WORLD_ROWS = SHARED_WORLD_ROWS;

// === Movement & Interaction ===
export const TACTICIAN_SPEED = 200;       // px/s player movement
export const PROXIMITY_THRESHOLD = 64;    // px for interactable detection
export const MOVE_THROTTLE_MS = 66;       // ~15fps network send rate

// === Timing (ms) ===
export const EMOTE_DURATION_MS = 3000;
export const ANIM_FADE_MS = 800;          // standard fade/tween duration
export const DUST_MOTE_INTERVAL_MS = 800; // ambient particle spawn rate
export const STATUS_PARTICLE_INTERVAL_MS = 2000;

/**
 * Minimum interval between dust-trail particle emits while the player walks.
 * Without throttling, the update loop emits every frame (~60Hz). 80ms caps
 * the rate at ~12Hz which is visually indistinguishable from continuous emit
 * while saving ~80% of particle spawns.
 */
export const DUST_EMIT_INTERVAL_MS = 80;

// === Spawn Grid ===
export const SPAWN_OFFSET = 48;           // px offset from zone edge for agent placement
export const SPAWN_GRID_SPACING = 48;     // px between agent spawn positions

/** Default tactician spawn point when no Tiled spawn point is provided. */
export const DEFAULT_SPAWN = { x: 416, y: 480 } as const;

/**
 * Legacy procedural floor extent used by the {@link OfficeScene.createFloor}
 * fallback. NOTE: this disagrees with the runtime worldWidth/worldHeight
 * (1600x896) — the procedural floor only paints the top-left 1280x720 area
 * to match the original (pre-50x28-map) layout. The Tiled map fills the full
 * 1600x896 extent. Kept separate to preserve the old fallback's appearance.
 */
export const LEGACY_FLOOR_EXTENT = { width: 1280, height: 720 } as const;

/**
 * Skylight grid coordinates (in tile units, multiplied by TILE_SIZE at use).
 * Order: department centres + central atrium.
 */
export const SKYLIGHT_POSITIONS: ReadonlyArray<{ x: number; y: number }> = [
  { x: 12, y: 7 },   // Engineering centre
  { x: 37, y: 7 },   // Research centre
  { x: 12, y: 21 },  // CRM centre
  { x: 37, y: 21 },  // Support centre
  { x: 24, y: 14 },  // Central atrium
];

/**
 * Zone particle emitter regions (in tile units, multiplied by TILE_SIZE at
 * use). Each entry covers the full rectangle the emitter samples from.
 */
export const ZONE_PARTICLE_REGIONS = {
  engineering: { x: 1, y: 2, w: 22, h: 2 },
  support: { x: 25, y: 16, w: 24, h: 12 },
  /** Atrium emitters use a single Y row with X spread; only x range + y are used. */
  atrium: { xMin: 10, xMax: 18, y: 15 },
} as const;

// === Visual ===
export const HALO_RADIUS = 14;            // px radius for agent status halo
export const HALO_Y_OFFSET = 4;           // px below sprite center
export const EMOTE_Y_OFFSET = -32;        // px above sprite for emote bubbles

// === Agent Behavior ===
export const AGENT_SPEED = 30;            // px/s slow patrol
export const WAYPOINT_INTERVAL_MIN = 3000; // ms
export const WAYPOINT_INTERVAL_MAX = 7000; // ms
export const ARRIVAL_THRESHOLD = 2;       // px

// === Virtual Joystick ===
export const JOYSTICK_BASE_RADIUS = 40;
export const JOYSTICK_THUMB_RADIUS = 16;
export const JOYSTICK_DEADZONE = 0.2;

// === Companion Behavior ===
export const COMPANION_SPEED = 180;       // slightly slower than player (200)
export const FOLLOW_DISTANCE = 28;        // px behind owner
export const LAG_FACTOR = 0.08;           // interpolation lag (lower = more delay)
