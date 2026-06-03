#!/usr/bin/env node
/**
 * preview-tileset.js
 *
 * Generates a local HTML page showing all tiles from all palette presets
 * as a visual catalog for designer review.
 *
 * Usage:
 *   node scripts/preview-tileset.js [--output path]
 *
 * Opens the generated HTML in the default browser.
 */

const { createCanvas } = require('@napi-rs/canvas');
const fs = require('node:fs');
const path = require('node:path');
const { renderPixelData } = require('./sprite-data/renderer');
const { getAllTiles, buildEnvColorMap, TILE_ORDER: FULL_TILE_ORDER } = require('./sprite-data/tile-definitions');
const palettePresets = require('../packages/shared-types/src/sprite-data/palette-presets.json');

function parseArgs() {
  const args = process.argv.slice(2);
  let output = path.resolve(__dirname, '..', 'apps', 'office-ui', 'public', 'tileset-preview.html');
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--output' && args[i + 1]) output = path.resolve(args[++i]);
  }
  return { output };
}

function tintColor(hex, tintHex, factor) {
  if (!tintHex || !hex?.startsWith('#')) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const tr = parseInt(tintHex.slice(1, 3), 16);
  const tg = parseInt(tintHex.slice(3, 5), 16);
  const tb = parseInt(tintHex.slice(5, 7), 16);
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return `#${clamp(r + (tr - r) * factor).toString(16).padStart(2, '0')}${clamp(g + (tg - g) * factor).toString(16).padStart(2, '0')}${clamp(b + (tb - b) * factor).toString(16).padStart(2, '0')}`;
}

function tintGrid(grid, tintHex, factor) {
  if (!tintHex) return grid;
  return grid.map((row) =>
    row.map((cell) => {
      if (cell === null) return null;
      if (cell.startsWith('#')) return tintColor(cell, tintHex, factor);
      return cell;
    }),
  );
}

const SCALE = 4;

async function main() {
  const { output } = parseArgs();

  const allTiles = getAllTiles();
  const sections = [];

  for (const [presetName, preset] of Object.entries(palettePresets.presets)) {
    const envColorMap = buildEnvColorMap(preset);
    const images = [];
    for (const tileName of FULL_TILE_ORDER) {
      const tileGrid = allTiles[tileName];
      if (!tileGrid) continue;

      // Resolve palette tokens and tint hex colors
      const resolved = tileGrid.map((row) =>
        row.map((cell) => {
          if (cell === null) return null;
          if (envColorMap[cell]) {
            const hex = envColorMap[cell];
            return preset.ambientTint ? tintColor(hex, preset.ambientTint, 0.1) : hex;
          }
          if (cell.startsWith('#')) return tintColor(cell, preset.ambientTint, 0.2);
          return cell;
        }),
      );

      const size = 32;
      const canvas = createCanvas(size * SCALE, size * SCALE);
      const ctx = canvas.getContext('2d');

      const tmpCanvas = createCanvas(size, size);
      const tmpCtx = tmpCanvas.getContext('2d');
      renderPixelData(tmpCtx, 0, 0, resolved, {});

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(tmpCanvas, 0, 0, size * SCALE, size * SCALE);

      const dataUrl = canvas.toDataURL('image/png');
      images.push({ name: tileName, dataUrl });
    }

    sections.push({ presetName, preset, images });
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Selva Tileset Preview</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; padding: 2rem; }
  h1 { font-size: 1.5rem; margin-bottom: 2rem; color: #a5b4fc; }
  .preset { margin-bottom: 2rem; }
  .preset h2 { font-size: 1.1rem; margin-bottom: 0.5rem; color: #818cf8; }
  .preset-meta { font-size: 0.75rem; color: #64748b; margin-bottom: 0.75rem; }
  .tiles { display: flex; gap: 8px; flex-wrap: wrap; }
  .tile { text-align: center; }
  .tile img { image-rendering: pixelated; border: 2px solid #334155; }
  .tile-name { font-size: 0.65rem; color: #94a3b8; margin-top: 4px; }
  .env-colors { display: flex; gap: 4px; margin-top: 4px; }
  .color-swatch { width: 16px; height: 16px; border: 1px solid #000; }
</style>
</head>
<body>
<h1>Selva Tileset Preview — All Palette Presets</h1>
${sections.map((s) => `
<div class="preset">
  <h2>${s.preset.name ?? s.presetName}</h2>
  <div class="preset-meta">
    ${s.preset.ambientTint ? `Ambient tint: ${s.preset.ambientTint}` : 'No ambient tint'}
  </div>
  <div class="env-colors">
    ${['floor', 'wall', 'deptEngineering', 'deptSales', 'deptSupport', 'deptResearch', 'reviewStation']
      .map((k) => `<div class="color-swatch" style="background:${s.preset[k]}" title="${k}: ${s.preset[k]}"></div>`)
      .join('')}
  </div>
  <div class="tiles">
    ${s.images.map((img) => `
    <div class="tile">
      <img src="${img.dataUrl}" width="${32 * SCALE}" height="${32 * SCALE}" alt="${img.name}">
      <div class="tile-name">${img.name}</div>
    </div>`).join('')}
  </div>
</div>`).join('\n')}
</body>
</html>`;

  fs.writeFileSync(output, html);
  console.log(`Wrote tileset preview: ${path.relative(process.cwd(), output)}`);
}

main().catch(console.error);
