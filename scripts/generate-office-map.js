#!/usr/bin/env node
//
// SOURCE OF TRUTH: packages/shared-types/src/world.ts — keep MAP_WIDTH,
// MAP_HEIGHT, and TILE_SIZE below in sync with WORLD_COLS, WORLD_ROWS,
// and TILE_SIZE_PX. This Node ESM script can't easily import from the TS
// package without a build step, so the numbers are duplicated here and
// validated by the assertion just above the constants block.
//
/**
 * generate-office-map.js
 *
 * Solarpunk "Living Office" layout generator.
 *
 * Programmatically constructs office-default.tmj — a 50x28 Tiled JSON map
 * with four biome departments, glass corridors, a central atrium garden,
 * and a blueprint gazebo.
 *
 * Layout concept (50 cols x 28 rows = 1600x896px):
 *
 *   Row 0-1:    Top bamboo wall border with windows
 *   Row 2-13:   Upper departments
 *     Col 1-22:    ENGINEERING (Tech Greenhouse)
 *     Col 23-24:   Glass corridor (vertical)
 *     Col 25-48:   RESEARCH (Library Garden)
 *   Row 14-15:  Central corridor (glass + water channel)
 *     Col 10-18:   CENTRAL ATRIUM (open garden)
 *     Col 35-42:   BLUEPRINT GAZEBO
 *   Row 16-27:  Lower departments
 *     Col 1-22:    CRM/GROWTH (Market Garden)
 *     Col 23-24:   Glass corridor (vertical)
 *     Col 25-48:   SUPPORT (Zen Garden)
 *   Row 27:     Bottom wall border
 *   Col 0:      Left wall border
 *   Col 49:     Right wall border
 *
 * Usage:
 *   node scripts/generate-office-map.js [--output path]
 */

const fs = require('node:fs');
const path = require('node:path');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
// MUST match packages/shared-types/src/world.ts (WORLD_COLS, WORLD_ROWS,
// TILE_SIZE_PX). Validated lazily via the readback assertion below.
const MAP_WIDTH = 50;
const MAP_HEIGHT = 28;
const TILE_SIZE = 32;

// Best-effort drift check: if the TS source-of-truth file is reachable on
// disk, verify the numbers match. We grep instead of importing because
// this script is plain Node ESM/CJS without a TS build step.
(function assertWorldConstantsInSync() {
  try {
    const worldTsPath = path.join(
      __dirname,
      '..',
      'packages',
      'shared-types',
      'src',
      'world.ts'
    );
    if (!fs.existsSync(worldTsPath)) return;
    const src = fs.readFileSync(worldTsPath, 'utf8');
    const expectations = [
      { name: 'TILE_SIZE_PX', expected: TILE_SIZE },
      { name: 'WORLD_COLS', expected: MAP_WIDTH },
      { name: 'WORLD_ROWS', expected: MAP_HEIGHT },
    ];
    for (const { name, expected } of expectations) {
      const match = src.match(
        new RegExp(`export const ${name} = (\\d+);`)
      );
      if (match && Number(match[1]) !== expected) {
        throw new Error(
          `world.ts ${name}=${match[1]} but generate-office-map.js has ${expected}. ` +
            `Update both, then re-run \`make generate-office-map\`.`
        );
      }
    }
  } catch (err) {
    // Drift assertion is best-effort. Surface drift but never block on
    // unrelated I/O issues.
    if (err && err.message && err.message.startsWith('world.ts ')) {
      throw err;
    }
  }
})();

// Tile IDs (1-indexed: tile_index + 1). Must match tile-definitions.js order.
const T = {
  EMPTY: 0,
  floor: 1,
  wall: 2,
  desk: 3,
  dept_engineering: 4,
  dept_sales: 5,
  dept_support: 6,
  dept_research: 7,
  review_station: 8,
  wall_top: 9,
  wall_bottom: 10,
  wall_left: 11,
  wall_right: 12,
  wall_corner_tl: 13,
  wall_corner_tr: 14,
  wall_corner_bl: 15,
  wall_corner_br: 16,
  wall_inner_tl: 17,
  wall_inner_tr: 18,
  wall_inner_bl: 19,
  wall_inner_br: 20,
  floor_corridor: 21,
  floor_lobby: 22,
  floor_carpet_blue: 23,
  floor_carpet_purple: 24,
  floor_carpet_green: 25,
  floor_carpet_brown: 26,
  floor_carpet_indigo: 27,
  floor_grid: 28,
  desk_front: 29,
  desk_side: 30,
  chair: 31,
  monitor: 32,
  monitor_on: 33,
  bookshelf: 34,
  plant_small: 35,
  plant_large: 36,
  whiteboard: 37,
  water_cooler: 38,
  coffee_machine: 39,
  filing_cabinet: 40,
  server_rack: 41,
  printer: 42,
  couch: 43,
  review_station_v2: 44,
  dispatch_terminal: 45,
  blueprint_table: 46,
  rug_round: 47,
  poster_a: 48,
  poster_b: 49,
  clock: 50,
  ceiling_light: 51,
  door_h: 52,
  door_v: 53,
  welcome_mat: 54,
  // FFVI-quality tiles (indices 54-78)
  desk_wood: 55,
  desk_with_coffee: 56,
  desk_with_papers: 57,
  monitor_active: 58,
  monitor_meeting: 59,
  chair_leather: 60,
  bookshelf_full: 61,
  plant_flowering: 62,
  plant_tall: 63,
  floor_shadow_s: 64,
  floor_shadow_e: 65,
  floor_light_pool: 66,
  ceiling_lamp_warm: 67,
  vent_grate: 68,
  whiteboard_scribbles: 69,
  sticky_notes: 70,
  coffee_machine_v2: 71,
  server_rack_active: 72,
  award_plaque: 73,
  clock_face: 74,
  wall_molding_top: 75,
  wall_baseboard: 76,
  window_day: 77,
  pillar: 78,
  rug_round_v2: 79,
};

// ---------------------------------------------------------------------------
// Layer helpers
// ---------------------------------------------------------------------------
function createLayer(fill = T.EMPTY) {
  return Array(MAP_WIDTH * MAP_HEIGHT).fill(fill);
}

function set(layer, col, row, tileId) {
  if (col >= 0 && col < MAP_WIDTH && row >= 0 && row < MAP_HEIGHT) {
    layer[row * MAP_WIDTH + col] = tileId;
  }
}

function fillRect(layer, x, y, w, h, tileId) {
  for (let r = y; r < y + h && r < MAP_HEIGHT; r++) {
    for (let c = x; c < x + w && c < MAP_WIDTH; c++) {
      set(layer, c, r, tileId);
    }
  }
}

// ---------------------------------------------------------------------------
// Zone definitions
// ---------------------------------------------------------------------------

// Biome departments
const ROOMS = [
  // -----------------------------------------------------------------------
  // ENGINEERING — Tech Greenhouse (upper-left)
  // -----------------------------------------------------------------------
  {
    name: 'Engineering',
    slug: 'dept-engineering',
    color: '#1a3d6b',
    // Interior zone (inside walls): cols 1-22, rows 2-13
    zone: { x: 1, y: 2, w: 22, h: 12 },
    floorTile: T.dept_engineering,
    doors: [
      // Door to vertical glass corridor (right side)
      { col: 22, row: 7, type: 'v' },
      { col: 22, row: 8, type: 'v' },
      // Door to central corridor (bottom)
      { col: 10, row: 13, type: 'h' },
      { col: 11, row: 13, type: 'h' },
    ],
    furniture: [
      // === Desk pod 1 (top-left, L-shaped) — monitors + bamboo desks ===
      { col: 2, row: 3, tile: T.desk_wood },
      { col: 3, row: 3, tile: T.desk_with_coffee },
      { col: 4, row: 3, tile: T.desk_side },
      { col: 2, row: 2, tile: T.monitor_active },
      { col: 3, row: 2, tile: T.monitor_active },
      { col: 4, row: 2, tile: T.monitor_on },
      { col: 2, row: 4, tile: T.chair_leather },
      { col: 3, row: 4, tile: T.chair_leather },
      { col: 4, row: 4, tile: T.chair },
      { col: 5, row: 4, tile: T.sticky_notes },

      // === Desk pod 2 (mid-left) ===
      { col: 8, row: 3, tile: T.desk_with_papers },
      { col: 9, row: 3, tile: T.desk_wood },
      { col: 8, row: 2, tile: T.monitor_active },
      { col: 9, row: 2, tile: T.monitor_meeting },
      { col: 8, row: 4, tile: T.chair_leather },
      { col: 9, row: 4, tile: T.chair },

      // === Desk pod 3 (lower row) ===
      { col: 2, row: 8, tile: T.desk_wood },
      { col: 3, row: 8, tile: T.desk_with_papers },
      { col: 4, row: 8, tile: T.desk_with_coffee },
      { col: 2, row: 7, tile: T.monitor_active },
      { col: 3, row: 7, tile: T.monitor_meeting },
      { col: 4, row: 7, tile: T.monitor_active },
      { col: 2, row: 9, tile: T.chair_leather },
      { col: 3, row: 9, tile: T.chair_leather },
      { col: 4, row: 9, tile: T.chair },
      { col: 5, row: 9, tile: T.sticky_notes },

      // === Server rack cluster (top-right corner) — the "greenhouse tech" ===
      { col: 18, row: 2, tile: T.server_rack_active },
      { col: 19, row: 2, tile: T.server_rack_active },
      { col: 20, row: 2, tile: T.server_rack },

      // === Greenery — the "greenhouse" part ===
      { col: 14, row: 2, tile: T.plant_tall },
      { col: 6, row: 6, tile: T.plant_large },
      { col: 13, row: 11, tile: T.plant_flowering },
      { col: 21, row: 11, tile: T.plant_tall },
      { col: 1, row: 12, tile: T.plant_small },
      { col: 7, row: 12, tile: T.plant_small },

      // Printer station
      { col: 14, row: 11, tile: T.printer },
    ],
    decorations: [
      // Warm lamps + light pools (golden solarpunk glow)
      { col: 6, row: 5, tile: T.ceiling_lamp_warm },
      { col: 6, row: 6, tile: T.floor_light_pool },
      { col: 15, row: 5, tile: T.ceiling_lamp_warm },
      { col: 15, row: 6, tile: T.floor_light_pool },
      // Shadows below furniture clusters
      { col: 2, row: 5, tile: T.floor_shadow_s },
      { col: 3, row: 5, tile: T.floor_shadow_s },
      { col: 4, row: 5, tile: T.floor_shadow_s },
      { col: 2, row: 10, tile: T.floor_shadow_s },
      { col: 3, row: 10, tile: T.floor_shadow_s },
      { col: 4, row: 10, tile: T.floor_shadow_s },
      // Shadow behind server racks
      { col: 21, row: 2, tile: T.floor_shadow_e },
      { col: 21, row: 3, tile: T.floor_shadow_e },
      // Whiteboard (scribbled diagrams) on north wall
      { col: 12, row: 2, tile: T.whiteboard_scribbles },
      // Windows on outer north wall
      { col: 5, row: 2, tile: T.window_day },
      { col: 16, row: 2, tile: T.window_day },
      // Award plaque
      { col: 17, row: 11, tile: T.award_plaque },
      // Vent
      { col: 10, row: 11, tile: T.vent_grate },
    ],
    review: { col: 18, row: 9 },
  },

  // -----------------------------------------------------------------------
  // RESEARCH — Library Garden (upper-right)
  // -----------------------------------------------------------------------
  {
    name: 'Research',
    slug: 'dept-research',
    color: '#1a4d3d',
    // Interior zone: cols 25-48, rows 2-13
    zone: { x: 25, y: 2, w: 24, h: 12 },
    floorTile: T.dept_research,
    doors: [
      // Door to vertical glass corridor (left side)
      { col: 25, row: 7, type: 'v' },
      { col: 25, row: 8, type: 'v' },
      // Door to central corridor (bottom)
      { col: 38, row: 13, type: 'h' },
      { col: 39, row: 13, type: 'h' },
    ],
    furniture: [
      // === Reading cluster 1 (left section) — desks with papers ===
      { col: 27, row: 3, tile: T.desk_with_papers },
      { col: 28, row: 3, tile: T.desk_wood },
      { col: 27, row: 2, tile: T.monitor_on },
      { col: 28, row: 2, tile: T.monitor_active },
      { col: 27, row: 4, tile: T.chair_leather },
      { col: 28, row: 4, tile: T.chair },

      // === Reading cluster 2 (mid section) ===
      { col: 33, row: 3, tile: T.desk_wood },
      { col: 34, row: 3, tile: T.desk_with_coffee },
      { col: 35, row: 3, tile: T.desk_side },
      { col: 33, row: 2, tile: T.monitor_active },
      { col: 34, row: 2, tile: T.monitor_meeting },
      { col: 35, row: 2, tile: T.monitor_on },
      { col: 33, row: 4, tile: T.chair_leather },
      { col: 34, row: 4, tile: T.chair_leather },
      { col: 35, row: 4, tile: T.chair },
      { col: 36, row: 4, tile: T.sticky_notes },

      // === Lower research pod ===
      { col: 27, row: 8, tile: T.desk_with_papers },
      { col: 28, row: 8, tile: T.desk_wood },
      { col: 27, row: 7, tile: T.monitor_active },
      { col: 28, row: 7, tile: T.monitor_on },
      { col: 27, row: 9, tile: T.chair_leather },
      { col: 28, row: 9, tile: T.chair },

      // === Library wall (right side) — bookshelves ===
      { col: 44, row: 2, tile: T.bookshelf_full },
      { col: 45, row: 2, tile: T.bookshelf_full },
      { col: 46, row: 2, tile: T.bookshelf },
      { col: 47, row: 2, tile: T.bookshelf_full },
      { col: 44, row: 6, tile: T.bookshelf_full },
      { col: 45, row: 6, tile: T.bookshelf },

      // === Garden greenery — the "library garden" ===
      { col: 31, row: 6, tile: T.plant_large },
      { col: 40, row: 2, tile: T.plant_tall },
      { col: 42, row: 10, tile: T.plant_flowering },
      { col: 47, row: 10, tile: T.plant_tall },
      { col: 26, row: 12, tile: T.plant_small },
      { col: 37, row: 12, tile: T.plant_flowering },
      { col: 30, row: 11, tile: T.plant_small },

      // Reading couch area
      { col: 40, row: 9, tile: T.couch },
      { col: 41, row: 9, tile: T.couch },

      // Filing cabinets
      { col: 46, row: 10, tile: T.filing_cabinet },
      { col: 47, row: 11, tile: T.filing_cabinet },
    ],
    decorations: [
      // Warm lamps
      { col: 30, row: 5, tile: T.ceiling_lamp_warm },
      { col: 30, row: 6, tile: T.floor_light_pool },
      { col: 42, row: 5, tile: T.ceiling_lamp_warm },
      { col: 42, row: 6, tile: T.floor_light_pool },
      // Shadows
      { col: 27, row: 5, tile: T.floor_shadow_s },
      { col: 28, row: 5, tile: T.floor_shadow_s },
      { col: 33, row: 5, tile: T.floor_shadow_s },
      { col: 34, row: 5, tile: T.floor_shadow_s },
      { col: 27, row: 10, tile: T.floor_shadow_s },
      { col: 28, row: 10, tile: T.floor_shadow_s },
      // Eastern shadow beside bookshelves
      { col: 48, row: 2, tile: T.floor_shadow_e },
      { col: 48, row: 6, tile: T.floor_shadow_e },
      // Windows on outer north wall
      { col: 30, row: 2, tile: T.window_day },
      { col: 38, row: 2, tile: T.window_day },
      // Windows on outer east wall
      { col: 48, row: 4, tile: T.window_day },
      { col: 48, row: 8, tile: T.window_day },
      // Whiteboard
      { col: 36, row: 2, tile: T.whiteboard_scribbles },
      // Clock + award
      { col: 43, row: 2, tile: T.clock_face },
      { col: 34, row: 11, tile: T.award_plaque },
      // Vent
      { col: 38, row: 11, tile: T.vent_grate },
      // Rug under reading area
      { col: 40, row: 10, tile: T.rug_round_v2 },
    ],
    review: { col: 44, row: 9 },
  },

  // -----------------------------------------------------------------------
  // CRM/GROWTH — Market Garden (lower-left)
  // -----------------------------------------------------------------------
  {
    name: 'Sales',
    slug: 'dept-sales',
    color: '#5a1d48',
    // Interior zone: cols 1-22, rows 16-27 (row 27 = bottom border, so interior rows 16-26)
    zone: { x: 1, y: 16, w: 22, h: 11 },
    floorTile: T.dept_sales,
    doors: [
      // Door to central corridor (top)
      { col: 10, row: 16, type: 'h' },
      { col: 11, row: 16, type: 'h' },
      // Door to vertical glass corridor (right)
      { col: 22, row: 21, type: 'v' },
      { col: 22, row: 22, type: 'v' },
    ],
    furniture: [
      // === Market desk pod 1 (herb station / CRM workspace) ===
      { col: 2, row: 18, tile: T.desk_with_coffee },
      { col: 3, row: 18, tile: T.desk_wood },
      { col: 4, row: 18, tile: T.desk_side },
      { col: 2, row: 17, tile: T.monitor_active },
      { col: 3, row: 17, tile: T.monitor_on },
      { col: 4, row: 17, tile: T.monitor_meeting },
      { col: 2, row: 19, tile: T.chair_leather },
      { col: 3, row: 19, tile: T.chair },
      { col: 4, row: 19, tile: T.chair },
      { col: 5, row: 19, tile: T.sticky_notes },

      // === Market desk pod 2 ===
      { col: 8, row: 18, tile: T.desk_wood },
      { col: 9, row: 18, tile: T.desk_with_papers },
      { col: 8, row: 17, tile: T.monitor_active },
      { col: 9, row: 17, tile: T.monitor_on },
      { col: 8, row: 19, tile: T.chair_leather },
      { col: 9, row: 19, tile: T.chair },

      // === Lower market pod ===
      { col: 2, row: 23, tile: T.desk_with_papers },
      { col: 3, row: 23, tile: T.desk_with_coffee },
      { col: 2, row: 22, tile: T.monitor_active },
      { col: 3, row: 22, tile: T.monitor_meeting },
      { col: 2, row: 24, tile: T.chair_leather },
      { col: 3, row: 24, tile: T.chair },
      { col: 4, row: 24, tile: T.sticky_notes },

      // === Cafe/herb station (market garden atmosphere) ===
      { col: 16, row: 17, tile: T.coffee_machine_v2 },
      { col: 17, row: 17, tile: T.water_cooler },
      { col: 15, row: 20, tile: T.couch },
      { col: 16, row: 20, tile: T.couch },

      // === Garden greenery ===
      { col: 14, row: 17, tile: T.plant_flowering },
      { col: 20, row: 17, tile: T.plant_tall },
      { col: 6, row: 22, tile: T.plant_large },
      { col: 19, row: 25, tile: T.plant_flowering },
      { col: 1, row: 26, tile: T.plant_small },
      { col: 12, row: 26, tile: T.plant_small },
      { col: 21, row: 26, tile: T.plant_tall },

      // Printer
      { col: 14, row: 25, tile: T.printer },
    ],
    decorations: [
      // Warm lamps
      { col: 6, row: 20, tile: T.ceiling_lamp_warm },
      { col: 6, row: 21, tile: T.floor_light_pool },
      { col: 15, row: 22, tile: T.ceiling_lamp_warm },
      { col: 15, row: 23, tile: T.floor_light_pool },
      // Shadows
      { col: 2, row: 20, tile: T.floor_shadow_s },
      { col: 3, row: 20, tile: T.floor_shadow_s },
      { col: 4, row: 20, tile: T.floor_shadow_s },
      { col: 2, row: 25, tile: T.floor_shadow_s },
      { col: 3, row: 25, tile: T.floor_shadow_s },
      // Windows on outer west wall
      { col: 1, row: 19, tile: T.window_day },
      { col: 1, row: 23, tile: T.window_day },
      // Windows on outer south wall
      { col: 5, row: 26, tile: T.window_day },
      { col: 15, row: 26, tile: T.window_day },
      // Whiteboard
      { col: 12, row: 17, tile: T.whiteboard_scribbles },
      // Clock + award
      { col: 18, row: 17, tile: T.clock_face },
      { col: 18, row: 25, tile: T.award_plaque },
      // Rug
      { col: 10, row: 21, tile: T.rug_round_v2 },
      // Vent
      { col: 8, row: 25, tile: T.vent_grate },
    ],
    review: { col: 18, row: 21 },
  },

  // -----------------------------------------------------------------------
  // SUPPORT — Zen Garden (lower-right)
  // -----------------------------------------------------------------------
  {
    name: 'Support',
    slug: 'dept-support',
    color: '#4a461d',
    // Interior zone: cols 25-48, rows 16-26
    zone: { x: 25, y: 16, w: 24, h: 11 },
    floorTile: T.dept_support,
    doors: [
      // Door to central corridor (top)
      { col: 38, row: 16, type: 'h' },
      { col: 39, row: 16, type: 'h' },
      // Door to vertical glass corridor (left)
      { col: 25, row: 21, type: 'v' },
      { col: 25, row: 22, type: 'v' },
    ],
    furniture: [
      // === Zen workspace pod 1 ===
      { col: 27, row: 18, tile: T.desk_with_coffee },
      { col: 28, row: 18, tile: T.desk_wood },
      { col: 27, row: 17, tile: T.monitor_active },
      { col: 28, row: 17, tile: T.monitor_on },
      { col: 27, row: 19, tile: T.chair_leather },
      { col: 28, row: 19, tile: T.chair },

      // === Zen workspace pod 2 ===
      { col: 33, row: 18, tile: T.desk_wood },
      { col: 34, row: 18, tile: T.desk_with_papers },
      { col: 35, row: 18, tile: T.desk_side },
      { col: 33, row: 17, tile: T.monitor_active },
      { col: 34, row: 17, tile: T.monitor_meeting },
      { col: 35, row: 17, tile: T.monitor_on },
      { col: 33, row: 19, tile: T.chair_leather },
      { col: 34, row: 19, tile: T.chair_leather },
      { col: 35, row: 19, tile: T.chair },
      { col: 36, row: 19, tile: T.sticky_notes },

      // === Meditation / quiet workspace (lower area) ===
      { col: 27, row: 23, tile: T.desk_with_papers },
      { col: 28, row: 23, tile: T.desk_with_coffee },
      { col: 27, row: 22, tile: T.monitor_active },
      { col: 28, row: 22, tile: T.monitor_on },
      { col: 27, row: 24, tile: T.chair_leather },
      { col: 28, row: 24, tile: T.chair },

      // === Bamboo screen / reading nook ===
      { col: 42, row: 17, tile: T.bookshelf_full },
      { col: 43, row: 17, tile: T.bookshelf },
      { col: 42, row: 20, tile: T.couch },
      { col: 43, row: 20, tile: T.couch },

      // === Zen garden greenery (heavy plants — the zen garden) ===
      { col: 38, row: 17, tile: T.plant_tall },
      { col: 46, row: 17, tile: T.plant_large },
      { col: 40, row: 22, tile: T.plant_flowering },
      { col: 45, row: 22, tile: T.plant_tall },
      { col: 47, row: 25, tile: T.plant_flowering },
      { col: 30, row: 25, tile: T.plant_small },
      { col: 36, row: 25, tile: T.plant_large },
      { col: 25, row: 26, tile: T.plant_small },
      { col: 44, row: 25, tile: T.plant_small },

      // Water cooler (water feature)
      { col: 46, row: 20, tile: T.water_cooler },
      // Filing
      { col: 46, row: 25, tile: T.filing_cabinet },
    ],
    decorations: [
      // Warm lamps
      { col: 30, row: 20, tile: T.ceiling_lamp_warm },
      { col: 30, row: 21, tile: T.floor_light_pool },
      { col: 40, row: 20, tile: T.ceiling_lamp_warm },
      { col: 40, row: 21, tile: T.floor_light_pool },
      // Shadows
      { col: 27, row: 20, tile: T.floor_shadow_s },
      { col: 28, row: 20, tile: T.floor_shadow_s },
      { col: 33, row: 20, tile: T.floor_shadow_s },
      { col: 34, row: 20, tile: T.floor_shadow_s },
      { col: 27, row: 25, tile: T.floor_shadow_s },
      { col: 28, row: 25, tile: T.floor_shadow_s },
      // Windows on outer east wall
      { col: 48, row: 19, tile: T.window_day },
      { col: 48, row: 23, tile: T.window_day },
      // Windows on outer south wall
      { col: 32, row: 26, tile: T.window_day },
      { col: 42, row: 26, tile: T.window_day },
      // Whiteboard
      { col: 37, row: 17, tile: T.whiteboard_scribbles },
      // Rug (meditation area)
      { col: 41, row: 21, tile: T.rug_round_v2 },
      { col: 34, row: 24, tile: T.rug_round_v2 },
      // Award + clock
      { col: 44, row: 17, tile: T.clock_face },
      { col: 32, row: 25, tile: T.award_plaque },
      // Vent
      { col: 38, row: 25, tile: T.vent_grate },
    ],
    review: { col: 44, row: 21 },
  },
];

// ---------------------------------------------------------------------------
// Blueprint Gazebo (in central corridor, right section)
// ---------------------------------------------------------------------------
const BLUEPRINT_ZONE = {
  name: 'Blueprint Lab',
  slug: 'dept-blueprint',
  color: '#1d3458',
  zone: { x: 35, y: 14, w: 8, h: 2 },
  floorTile: T.floor_carpet_indigo,
  furniture: [
    { col: 37, row: 14, tile: T.blueprint_table },
    { col: 40, row: 14, tile: T.blueprint_table },
  ],
  decorations: [
    { col: 38, row: 14, tile: T.ceiling_lamp_warm },
    { col: 39, row: 15, tile: T.floor_light_pool },
  ],
};

// ---------------------------------------------------------------------------
// Central Atrium — open garden hub
// ---------------------------------------------------------------------------
const ATRIUM = {
  zone: { x: 10, y: 14, w: 9, h: 2 },
  floorTile: T.floor_lobby,
  furniture: [
    // Garden plants surrounding the atrium
    { col: 10, row: 14, tile: T.plant_large },
    { col: 18, row: 14, tile: T.plant_large },
    { col: 10, row: 15, tile: T.plant_flowering },
    { col: 18, row: 15, tile: T.plant_flowering },
    { col: 14, row: 14, tile: T.plant_tall },
  ],
  decorations: [
    { col: 12, row: 14, tile: T.ceiling_lamp_warm },
    { col: 12, row: 15, tile: T.floor_light_pool },
    { col: 16, row: 14, tile: T.ceiling_lamp_warm },
    { col: 16, row: 15, tile: T.floor_light_pool },
    // Rug at atrium center
    { col: 14, row: 15, tile: T.rug_round_v2 },
  ],
};

// ---------------------------------------------------------------------------
// Vertical glass corridor furniture & decoration
// ---------------------------------------------------------------------------
const GLASS_CORRIDOR = {
  furniture: [
    // Plants at corridor-department intersections (solarpunk greenery along glass)
    { col: 23, row: 3, tile: T.plant_small },
    { col: 24, row: 3, tile: T.plant_small },
    { col: 23, row: 12, tile: T.plant_flowering },
    { col: 24, row: 12, tile: T.plant_small },
    { col: 23, row: 17, tile: T.plant_small },
    { col: 24, row: 17, tile: T.plant_flowering },
    { col: 23, row: 25, tile: T.plant_small },
    { col: 24, row: 25, tile: T.plant_small },
  ],
  decorations: [
    // Lamps along vertical glass corridor
    { col: 23, row: 6, tile: T.ceiling_lamp_warm },
    { col: 23, row: 7, tile: T.floor_light_pool },
    { col: 24, row: 20, tile: T.ceiling_lamp_warm },
    { col: 24, row: 21, tile: T.floor_light_pool },
    // Pillars at corridor transitions
    { col: 23, row: 9, tile: T.pillar },
    { col: 24, row: 9, tile: T.pillar },
    { col: 23, row: 23, tile: T.pillar },
    { col: 24, row: 23, tile: T.pillar },
  ],
};

// ---------------------------------------------------------------------------
// Central corridor horizontal decorations
// ---------------------------------------------------------------------------
const CENTRAL_CORRIDOR_DECO = {
  furniture: [
    // Break station near atrium
    { col: 6, row: 14, tile: T.coffee_machine_v2 },
    { col: 7, row: 14, tile: T.water_cooler },
    { col: 6, row: 15, tile: T.couch },
    { col: 7, row: 15, tile: T.couch },
    // Welcome mat at atrium entries
    { col: 20, row: 14, tile: T.plant_small },
    { col: 20, row: 15, tile: T.plant_small },
    // Plants along central corridor edges
    { col: 2, row: 14, tile: T.plant_small },
    { col: 30, row: 14, tile: T.plant_small },
    { col: 45, row: 14, tile: T.plant_small },
    { col: 47, row: 15, tile: T.plant_flowering },
  ],
  decorations: [
    // Lamps along the horizontal corridor
    { col: 4, row: 14, tile: T.ceiling_lamp_warm },
    { col: 4, row: 15, tile: T.floor_light_pool },
    { col: 28, row: 14, tile: T.ceiling_lamp_warm },
    { col: 28, row: 15, tile: T.floor_light_pool },
    { col: 45, row: 14, tile: T.ceiling_lamp_warm },
    { col: 45, row: 15, tile: T.floor_light_pool },
  ],
};

// ---------------------------------------------------------------------------
// Dispatch stations (in central atrium area)
// ---------------------------------------------------------------------------
const DISPATCH_STATIONS = [
  { col: 13, row: 14, label: 'Dispatch Task' },
  { col: 15, row: 15, label: 'Dispatch Task' },
];

// ---------------------------------------------------------------------------
// Spawn points (near central atrium)
// ---------------------------------------------------------------------------
const SPAWN_POINTS = [
  { col: 13, row: 15, name: 'default-spawn' },
  { col: 15, row: 14, name: 'spawn-2' },
  { col: 24, row: 14, name: 'spawn-3' },
];

// ---------------------------------------------------------------------------
// Layer generators
// ---------------------------------------------------------------------------

/**
 * Floor layer: each zone gets its biome tile, corridors get floor_corridor,
 * atrium gets floor_lobby, and border row/col gets EMPTY (walls drawn there).
 */
function generateFloorLayer() {
  const layer = createLayer(T.EMPTY);

  // 1) Fill the entire interior with corridor floor as a base
  fillRect(layer, 1, 1, MAP_WIDTH - 2, MAP_HEIGHT - 2, T.floor_corridor);

  // 2) Department biome floors
  for (const room of ROOMS) {
    const z = room.zone;
    fillRect(layer, z.x, z.y, z.w, z.h, room.floorTile);
  }

  // 3) Vertical glass corridor (cols 23-24, rows 2-13 and 16-26)
  //    These are already floor_corridor from the base fill, but ensure
  //    they stay corridor even if a department zone overlapped.
  fillRect(layer, 23, 2, 2, 12, T.floor_corridor);
  fillRect(layer, 23, 16, 2, 11, T.floor_corridor);

  // 4) Central horizontal corridor (rows 14-15, full width)
  fillRect(layer, 1, 14, MAP_WIDTH - 2, 2, T.floor_corridor);

  // 5) Central Atrium garden (floor_lobby)
  const az = ATRIUM.zone;
  fillRect(layer, az.x, az.y, az.w, az.h, ATRIUM.floorTile);

  // 6) Blueprint Gazebo
  const bz = BLUEPRINT_ZONE.zone;
  fillRect(layer, bz.x, bz.y, bz.w, bz.h, BLUEPRINT_ZONE.floorTile);

  return layer;
}

/**
 * Walls layer: outer border with bamboo walls + windows, internal walls
 * between departments using wall variants, doors where corridors meet rooms.
 */
function generateWallsLayer() {
  const layer = createLayer(T.EMPTY);

  // --- Outer border ---

  // Top row (row 0): wall_molding_top with corner variants
  set(layer, 0, 0, T.wall_corner_tl);
  set(layer, MAP_WIDTH - 1, 0, T.wall_corner_tr);
  for (let c = 1; c < MAP_WIDTH - 1; c++) {
    set(layer, c, 0, T.wall_molding_top);
  }

  // Bottom row (row 27)
  set(layer, 0, MAP_HEIGHT - 1, T.wall_corner_bl);
  set(layer, MAP_WIDTH - 1, MAP_HEIGHT - 1, T.wall_corner_br);
  for (let c = 1; c < MAP_WIDTH - 1; c++) {
    set(layer, c, MAP_HEIGHT - 1, T.wall_bottom);
  }

  // Left column (col 0)
  for (let r = 1; r < MAP_HEIGHT - 1; r++) {
    set(layer, 0, r, T.wall_left);
  }

  // Right column (col 49)
  for (let r = 1; r < MAP_HEIGHT - 1; r++) {
    set(layer, MAP_WIDTH - 1, r, T.wall_right);
  }

  // --- Row 1: inner top wall of upper departments (bamboo frame) ---
  for (let c = 1; c < MAP_WIDTH - 1; c++) {
    set(layer, c, 1, T.wall_molding_top);
  }

  // --- Row 13: bottom wall of upper departments / top wall of corridor ---
  for (let c = 1; c < 23; c++) {
    set(layer, c, 13, T.wall_bottom);
  }
  for (let c = 25; c < MAP_WIDTH - 1; c++) {
    set(layer, c, 13, T.wall_bottom);
  }
  // Glass corridor columns at row 13
  set(layer, 23, 13, T.wall_bottom);
  set(layer, 24, 13, T.wall_bottom);

  // --- Row 16: top wall of lower departments / bottom wall of corridor ---
  for (let c = 1; c < 23; c++) {
    set(layer, c, 16, T.wall_molding_top);
  }
  for (let c = 25; c < MAP_WIDTH - 1; c++) {
    set(layer, c, 16, T.wall_molding_top);
  }
  // Glass corridor columns at row 16
  set(layer, 23, 16, T.wall_molding_top);
  set(layer, 24, 16, T.wall_molding_top);

  // --- Row 26: bottom inner wall of lower departments ---
  for (let c = 1; c < MAP_WIDTH - 1; c++) {
    set(layer, c, 26, T.wall_bottom);
  }

  // --- Vertical divider: col 22 (right wall of left departments) ---
  for (let r = 1; r <= 13; r++) {
    set(layer, 22, r, T.wall_right);
  }
  for (let r = 16; r <= 26; r++) {
    set(layer, 22, r, T.wall_right);
  }

  // --- Vertical divider: col 25 (left wall of right departments) ---
  for (let r = 1; r <= 13; r++) {
    set(layer, 25, r, T.wall_left);
  }
  for (let r = 16; r <= 26; r++) {
    set(layer, 25, r, T.wall_left);
  }

  // --- Inner corners ---
  // Top-left Engineering
  set(layer, 0, 1, T.wall_corner_tl);
  // Where vertical dividers meet horizontal walls
  set(layer, 22, 1, T.wall_corner_tr);
  set(layer, 25, 1, T.wall_corner_tl);
  set(layer, 22, 13, T.wall_corner_br);
  set(layer, 25, 13, T.wall_corner_bl);
  set(layer, 22, 16, T.wall_corner_tr);
  set(layer, 25, 16, T.wall_corner_tl);
  set(layer, 22, 26, T.wall_corner_br);
  set(layer, 25, 26, T.wall_corner_bl);

  // --- Doors: punch holes in walls ---
  const allDoors = [];
  for (const room of ROOMS) {
    allDoors.push(...room.doors);
  }
  for (const door of allDoors) {
    set(layer, door.col, door.row, door.type === 'h' ? T.door_h : T.door_v);
  }

  return layer;
}

/**
 * Furniture layer: department-specific furniture clusters plus corridor
 * amenities and dispatch terminals.
 */
function generateFurnitureLayer() {
  const layer = createLayer(T.EMPTY);

  // Room furniture
  for (const room of ROOMS) {
    for (const f of room.furniture) {
      set(layer, f.col, f.row, f.tile);
    }
  }

  // Blueprint gazebo furniture
  for (const f of BLUEPRINT_ZONE.furniture) {
    set(layer, f.col, f.row, f.tile);
  }

  // Atrium furniture (garden plants)
  for (const f of ATRIUM.furniture) {
    set(layer, f.col, f.row, f.tile);
  }

  // Glass corridor furniture
  for (const f of GLASS_CORRIDOR.furniture) {
    set(layer, f.col, f.row, f.tile);
  }

  // Central corridor furniture
  for (const f of CENTRAL_CORRIDOR_DECO.furniture) {
    set(layer, f.col, f.row, f.tile);
  }

  // Dispatch terminals
  for (const d of DISPATCH_STATIONS) {
    set(layer, d.col, d.row, T.dispatch_terminal);
  }

  return layer;
}

/**
 * Decorations layer: lamps, shadows, windows, plaques, rugs, vents.
 */
function generateDecorationsLayer() {
  const layer = createLayer(T.EMPTY);

  for (const room of ROOMS) {
    for (const d of room.decorations) {
      set(layer, d.col, d.row, d.tile);
    }
  }

  for (const d of BLUEPRINT_ZONE.decorations) {
    set(layer, d.col, d.row, d.tile);
  }

  for (const d of ATRIUM.decorations) {
    set(layer, d.col, d.row, d.tile);
  }

  for (const d of GLASS_CORRIDOR.decorations) {
    set(layer, d.col, d.row, d.tile);
  }

  for (const d of CENTRAL_CORRIDOR_DECO.decorations) {
    set(layer, d.col, d.row, d.tile);
  }

  return layer;
}

/**
 * Collision layer: walls and solid furniture block movement.
 * Doors, rugs, lamps, shadows, sticky notes, vents are walkable.
 */
function generateCollisionLayer(wallsLayer, furnitureLayer) {
  const layer = createLayer(T.EMPTY);
  const COLLISION_MARKER = T.wall;

  // Non-collidable furniture (decorative / walkable)
  const WALKABLE_FURNITURE = new Set([
    T.rug_round, T.rug_round_v2, T.ceiling_light, T.ceiling_lamp_warm,
    T.welcome_mat, T.sticky_notes, T.floor_shadow_s, T.floor_shadow_e,
    T.floor_light_pool, T.vent_grate,
  ]);

  for (let i = 0; i < MAP_WIDTH * MAP_HEIGHT; i++) {
    const wallTile = wallsLayer[i];
    const furnitureTile = furnitureLayer[i];

    // Walls block (except doors)
    if (wallTile !== T.EMPTY && wallTile !== T.door_h && wallTile !== T.door_v) {
      layer[i] = COLLISION_MARKER;
    }

    // Solid furniture blocks
    if (furnitureTile !== T.EMPTY && !WALKABLE_FURNITURE.has(furnitureTile)) {
      layer[i] = COLLISION_MARKER;
    }
  }

  return layer;
}

// ---------------------------------------------------------------------------
// Object group generators
// ---------------------------------------------------------------------------

function generateDepartmentObjects() {
  let nextId = 1;
  const objects = [];

  for (const room of ROOMS) {
    const z = room.zone;
    objects.push({
      id: nextId++,
      name: room.name,
      type: '',
      x: z.x * TILE_SIZE,
      y: z.y * TILE_SIZE,
      width: z.w * TILE_SIZE,
      height: z.h * TILE_SIZE,
      properties: [
        { name: 'slug', type: 'string', value: room.slug },
        { name: 'name', type: 'string', value: room.name },
        { name: 'color', type: 'string', value: room.color },
        { name: 'maxAgents', type: 'int', value: 4 },
      ],
      visible: true,
    });
  }

  // Blueprint zone (maxAgents: 0 — no agents patrol here)
  const bz = BLUEPRINT_ZONE.zone;
  objects.push({
    id: nextId++,
    name: BLUEPRINT_ZONE.name,
    type: '',
    x: bz.x * TILE_SIZE,
    y: bz.y * TILE_SIZE,
    width: bz.w * TILE_SIZE,
    height: bz.h * TILE_SIZE,
    properties: [
      { name: 'slug', type: 'string', value: BLUEPRINT_ZONE.slug },
      { name: 'name', type: 'string', value: BLUEPRINT_ZONE.name },
      { name: 'color', type: 'string', value: BLUEPRINT_ZONE.color },
      { name: 'maxAgents', type: 'int', value: 0 },
    ],
    visible: true,
  });

  return { objects, nextId };
}

function generateReviewStationObjects(startId) {
  let nextId = startId;
  const objects = [];

  for (const room of ROOMS) {
    if (room.review) {
      objects.push({
        id: nextId++,
        name: 'review-station',
        type: '',
        x: room.review.col * TILE_SIZE,
        y: room.review.row * TILE_SIZE,
        width: TILE_SIZE,
        height: TILE_SIZE,
        properties: [
          { name: 'departmentSlug', type: 'string', value: room.slug },
        ],
        visible: true,
      });
    }
  }

  return { objects, nextId };
}

function generateInteractableObjects(startId) {
  let nextId = startId;
  const objects = [];

  // Dispatch stations
  for (const d of DISPATCH_STATIONS) {
    objects.push({
      id: nextId++,
      name: 'dispatch-station',
      type: '',
      x: d.col * TILE_SIZE,
      y: d.row * TILE_SIZE,
      width: TILE_SIZE,
      height: TILE_SIZE,
      properties: [
        { name: 'interactType', type: 'string', value: 'dispatch' },
        { name: 'label', type: 'string', value: d.label },
      ],
      visible: true,
    });
  }

  // Blueprint interactable (in the gazebo)
  objects.push({
    id: nextId++,
    name: 'blueprint-station',
    type: '',
    x: 39 * TILE_SIZE,
    y: 14 * TILE_SIZE,
    width: TILE_SIZE,
    height: TILE_SIZE,
    properties: [
      { name: 'interactType', type: 'string', value: 'blueprint' },
      { name: 'label', type: 'string', value: 'Blueprint Editor' },
    ],
    visible: true,
  });

  return { objects, nextId };
}

function generateSpawnPointObjects(startId) {
  let nextId = startId;
  const objects = [];

  for (const sp of SPAWN_POINTS) {
    objects.push({
      id: nextId++,
      name: sp.name,
      type: '',
      x: sp.col * TILE_SIZE,
      y: sp.row * TILE_SIZE,
      width: TILE_SIZE,
      height: TILE_SIZE,
      visible: true,
    });
  }

  return { objects, nextId };
}

// ---------------------------------------------------------------------------
// TMJ builder
// ---------------------------------------------------------------------------

function buildTmj() {
  const floorLayer = generateFloorLayer();
  const wallsLayer = generateWallsLayer();
  const furnitureLayer = generateFurnitureLayer();
  const decorationsLayer = generateDecorationsLayer();
  const collisionLayer = generateCollisionLayer(wallsLayer, furnitureLayer);

  const { objects: deptObjects, nextId: id1 } = generateDepartmentObjects();
  const { objects: reviewObjects, nextId: id2 } = generateReviewStationObjects(id1);
  const { objects: interactableObjects, nextId: id3 } = generateInteractableObjects(id2);
  const { objects: spawnObjects, nextId: nextObjectId } = generateSpawnPointObjects(id3);

  const tileCount = 79; // 54 original + 25 FFVI tiles

  const layers = [
    {
      id: 1,
      name: 'floor',
      type: 'tilelayer',
      x: 0, y: 0,
      width: MAP_WIDTH,
      height: MAP_HEIGHT,
      data: floorLayer,
      visible: true,
      opacity: 1,
    },
    {
      id: 2,
      name: 'walls',
      type: 'tilelayer',
      x: 0, y: 0,
      width: MAP_WIDTH,
      height: MAP_HEIGHT,
      data: wallsLayer,
      visible: true,
      opacity: 1,
    },
    {
      id: 3,
      name: 'furniture',
      type: 'tilelayer',
      x: 0, y: 0,
      width: MAP_WIDTH,
      height: MAP_HEIGHT,
      data: furnitureLayer,
      visible: true,
      opacity: 1,
    },
    {
      id: 4,
      name: 'decorations',
      type: 'tilelayer',
      x: 0, y: 0,
      width: MAP_WIDTH,
      height: MAP_HEIGHT,
      data: decorationsLayer,
      visible: true,
      opacity: 1,
    },
    {
      id: 5,
      name: 'collision',
      type: 'tilelayer',
      x: 0, y: 0,
      width: MAP_WIDTH,
      height: MAP_HEIGHT,
      data: collisionLayer,
      visible: true,
      opacity: 1,
    },
    {
      id: 6,
      name: 'departments',
      type: 'objectgroup',
      x: 0, y: 0,
      objects: deptObjects,
      visible: true,
      opacity: 1,
    },
    {
      id: 7,
      name: 'review-stations',
      type: 'objectgroup',
      x: 0, y: 0,
      objects: reviewObjects,
      visible: true,
      opacity: 1,
    },
    {
      id: 8,
      name: 'interactables',
      type: 'objectgroup',
      x: 0, y: 0,
      objects: interactableObjects,
      visible: true,
      opacity: 1,
    },
    {
      id: 9,
      name: 'spawn-points',
      type: 'objectgroup',
      x: 0, y: 0,
      objects: spawnObjects,
      visible: true,
      opacity: 1,
    },
  ];

  const tileRows = Math.ceil(tileCount / 16);
  return {
    compressionlevel: -1,
    height: MAP_HEIGHT,
    width: MAP_WIDTH,
    infinite: false,
    layers,
    nextlayerid: layers.length + 1,
    nextobjectid: nextObjectId,
    orientation: 'orthogonal',
    renderorder: 'right-down',
    tileheight: TILE_SIZE,
    tilewidth: TILE_SIZE,
    tilesets: [
      {
        firstgid: 1,
        name: 'office-tileset',
        tilewidth: TILE_SIZE,
        tileheight: TILE_SIZE,
        tilecount: tileCount,
        columns: 16,
        image: '../tilesets/office-tileset.png',
        imagewidth: 512,
        imageheight: tileRows * TILE_SIZE,
      },
    ],
    type: 'map',
    version: '1.10',
    tiledversion: '1.11.0',
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  const args = process.argv.slice(2);
  let outputPath = path.resolve(
    __dirname, '..', 'apps', 'office-ui', 'public', 'assets', 'maps', 'office-default.tmj'
  );

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--output' && args[i + 1]) {
      outputPath = path.resolve(args[++i]);
    }
  }

  const tmj = buildTmj();
  const json = JSON.stringify(tmj, null, 2);

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, json);

  const relPath = path.relative(process.cwd(), outputPath);
  const stats = {
    layers: tmj.layers.length,
    tiles: `${MAP_WIDTH}x${MAP_HEIGHT}`,
    pixels: `${MAP_WIDTH * TILE_SIZE}x${MAP_HEIGHT * TILE_SIZE}`,
    bytes: json.length,
  };
  console.log(`Generated ${relPath}`);
  console.log(`  ${stats.layers} layers, ${stats.tiles} tiles (${stats.pixels}px), ${stats.bytes} bytes`);

  // Validate: count non-empty tiles per layer
  for (const layer of tmj.layers) {
    if (layer.type === 'tilelayer' && layer.data) {
      const nonEmpty = layer.data.filter(t => t !== 0).length;
      console.log(`  ${layer.name}: ${nonEmpty} tiles`);
    } else if (layer.type === 'objectgroup' && layer.objects) {
      console.log(`  ${layer.name}: ${layer.objects.length} objects`);
    }
  }
}

main();
