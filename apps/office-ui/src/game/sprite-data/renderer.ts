/**
 * Browser/Phaser pixel-data renderer.
 * Same logic as scripts/sprite-data/renderer.js in TypeScript.
 */
import type { PixelGrid } from '@autoswarm/shared-types';

/**
 * Render a pixel-data grid onto a canvas context.
 */
export function renderPixelData(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  grid: PixelGrid,
  colorMap: Record<string, string>,
): void {
  for (let row = 0; row < grid.length; row++) {
    const line = grid[row];
    for (let col = 0; col < line.length; col++) {
      const token = line[col];
      if (token == null) continue;
      const color = token.startsWith('#') ? token : colorMap[token];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(x + col, y + row, 1, 1);
    }
  }
}

/**
 * Compose multiple layers onto a canvas context.
 * Layers painted in order (first = bottom, last = top).
 */
export function composeLayers(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  layers: (PixelGrid | null | undefined)[],
  colorMap: Record<string, string>,
): void {
  for (const layer of layers) {
    if (layer) {
      renderPixelData(ctx, x, y, layer, colorMap);
    }
  }
}
