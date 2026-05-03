/**
 * World dimensions — the canonical source of truth for the office grid.
 *
 * Every consumer (Colyseus server bounds checks, Phaser scene worldBounds,
 * the .tmj map generator) MUST derive its numbers from this module so the
 * three layers cannot drift apart.
 *
 * If you change WORLD_COLS/WORLD_ROWS here you also need to:
 *   - regenerate the default Tiled map (`make generate-office-map`)
 *   - re-run Colyseus tests (the bounds tests assert exact integers)
 *   - audit any hard-coded camera/world setup in OfficeScene.ts
 */

/** Pixel width of one Tiled tile. Must match the tileset's `tilewidth`. */
export const TILE_SIZE_PX = 32;

/** Office grid width in tiles. */
export const WORLD_COLS = 50;

/** Office grid height in tiles. */
export const WORLD_ROWS = 28;

/** Office width in pixels (TILE_SIZE_PX * WORLD_COLS). */
export const WORLD_WIDTH_PX = TILE_SIZE_PX * WORLD_COLS;

/** Office height in pixels (TILE_SIZE_PX * WORLD_ROWS). */
export const WORLD_HEIGHT_PX = TILE_SIZE_PX * WORLD_ROWS;

/**
 * Canonical movement bounds used by Colyseus position validation. Origin is
 * top-left; max values are inclusive (a player on the rightmost column is
 * still inside the world).
 */
export const OFFICE_BOUNDS = {
  minX: 0,
  minY: 0,
  maxX: WORLD_WIDTH_PX,
  maxY: WORLD_HEIGHT_PX,
} as const;

export type OfficeBounds = typeof OFFICE_BOUNDS;
