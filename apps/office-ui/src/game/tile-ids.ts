/**
 * Furniture / decoration tile indices in the office tileset.
 *
 * The IDs are 1-based, matching how Tiled stores tile gids in TMJ map files.
 * The same tile can play multiple roles depending on the map theme — for
 * example, tile 39 is "coffee_machine" in the engineering map and the same
 * sprite is repurposed as "water_cooler" in the wellness/zen map. We export
 * both names so each animation handler in {@link OfficeScene} reads with the
 * semantic alias that matches its intent. The numeric values are intentionally
 * shared.
 */

// === Canonical names (the original tileset definitions) ===
export const TILE_MONITOR_ON = 33;
export const TILE_PLANT_SMALL = 35;
export const TILE_PLANT_LARGE = 36;
export const TILE_COFFEE_MACHINE = 39;
export const TILE_SERVER_RACK = 41;

// === Semantic aliases (same physical tile, different role per map theme) ===
/** Wellness/zen map repurposes the coffee machine sprite as a water cooler. */
export const TILE_WATER_COOLER = TILE_COFFEE_MACHINE;
/** Some maps render the small-plant tile as a candle prop. */
export const TILE_CANDLE = TILE_PLANT_SMALL;
/** Some maps render the server-rack tile as a grow light prop. */
export const TILE_GROW_LIGHT = TILE_SERVER_RACK;
