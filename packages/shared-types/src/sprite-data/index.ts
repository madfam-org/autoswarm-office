/** A 2D grid of pixel tokens. null = transparent. */
export type PixelGrid = (string | null)[][];

/** A sprite template with dimensions and pixel data. */
export interface SpriteTemplate {
  width: number;
  height: number;
  pixels: PixelGrid;
}

/** Re-export palette and color resolver */
export { resolveColorMap, darken, lighten } from './resolve-colors';
