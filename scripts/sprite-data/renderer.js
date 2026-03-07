/**
 * Node.js pixel-data renderer for build-time sprite generation.
 * Shared rendering logic used by generate-assets.js.
 */

/**
 * Render a pixel-data grid onto a canvas context.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} x - left offset on canvas
 * @param {number} y - top offset on canvas
 * @param {(string|null)[][]} grid - 2D array of color tokens or hex values
 * @param {Record<string, string>} colorMap - maps tokens to hex colors
 */
function renderPixelData(ctx, x, y, grid, colorMap) {
  for (let row = 0; row < grid.length; row++) {
    const line = grid[row];
    for (let col = 0; col < line.length; col++) {
      const token = line[col];
      if (token == null) continue;
      // Direct hex string (starts with #) or resolve via colorMap
      const color = token.startsWith('#') ? token : colorMap[token];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(x + col, y + row, 1, 1);
    }
  }
}

/**
 * Compose multiple layers onto a canvas context.
 * Layers are painted in order (first = bottom, last = top).
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} x - left offset
 * @param {number} y - top offset
 * @param {(string|null)[][][]} layers - array of pixel grids
 * @param {Record<string, string>} colorMap - token-to-color mapping
 */
function composeLayers(ctx, x, y, layers, colorMap) {
  for (const layer of layers) {
    if (layer) {
      renderPixelData(ctx, x, y, layer, colorMap);
    }
  }
}

module.exports = { renderPixelData, composeLayers };
