/**
 * generate-assets.js
 *
 * Generates pixel-art sprite PNGs from pixel-data templates.
 * Uses @napi-rs/canvas to render templates defined in
 * packages/shared-types/src/sprite-data/*.json
 *
 * Usage:  node scripts/generate-assets.js
 */

const { createCanvas } = require('@napi-rs/canvas');
const fs = require('node:fs');
const path = require('node:path');
const { renderPixelData, composeLayers } = require('./sprite-data/renderer');

// ---------------------------------------------------------------------------
// Template data
// ---------------------------------------------------------------------------
const bodyTemplates = require('../packages/shared-types/src/sprite-data/body.json');
const hairTemplates = require('../packages/shared-types/src/sprite-data/hair.json');
const accessories = require('../packages/shared-types/src/sprite-data/accessories.json');
const emoteTemplates = require('../packages/shared-types/src/sprite-data/emotes.json');
const tileTemplates = require('../packages/shared-types/src/sprite-data/tiles.json');
const iconTemplates = require('../packages/shared-types/src/sprite-data/icons.json');

// ---------------------------------------------------------------------------
// Color utilities (shared logic — also in resolve-colors.ts)
// ---------------------------------------------------------------------------
function darken(hex, factor) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `#${Math.round(r * (1 - factor)).toString(16).padStart(2, '0')}${Math.round(g * (1 - factor)).toString(16).padStart(2, '0')}${Math.round(b * (1 - factor)).toString(16).padStart(2, '0')}`;
}

function lighten(hex, factor) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `#${Math.round(r + (255 - r) * factor).toString(16).padStart(2, '0')}${Math.round(g + (255 - g) * factor).toString(16).padStart(2, '0')}${Math.round(b + (255 - b) * factor).toString(16).padStart(2, '0')}`;
}

/**
 * Build a color map for a role color (agent sprites, tactician).
 */
function buildColorMap(roleColor, skinColor = '#fcd5b0', hairColor = '#4a3728') {
  return {
    S: skinColor,
    K: darken(skinColor, 0.15),
    O: '#0f0f1a',
    H: hairColor,
    C: roleColor,
    D: darken(roleColor, 0.15),
    L: lighten(roleColor, 0.2),
    E: '#0f0f1a',
    W: '#ffffff',
    X: darken(roleColor, 0.3),
    G: lighten(roleColor, 0.3),
    B: darken(roleColor, 0.25),
    P: darken(roleColor, 0.3),
    R: darken(roleColor, 0.4),
  };
}

// ---------------------------------------------------------------------------
// Color palette — mirrors BootScene.ts
// ---------------------------------------------------------------------------
const COLORS = {
  tactician: '#6366f1',
  planner: '#8b5cf6',
  coder: '#06b6d4',
  reviewer: '#f59e0b',
  researcher: '#10b981',
  crm: '#f43f5e',
  support: '#0ea5e9',
};

// ---------------------------------------------------------------------------
// Directories
// ---------------------------------------------------------------------------
const ASSETS_ROOT = path.resolve(__dirname, '..', 'apps', 'office-ui', 'public', 'assets');
const DIRS = {
  sprites: path.join(ASSETS_ROOT, 'sprites'),
  tilesets: path.join(ASSETS_ROOT, 'tilesets'),
  ui: path.join(ASSETS_ROOT, 'ui'),
};

// ---------------------------------------------------------------------------
// Direction/walk frame mapping for body templates
// ---------------------------------------------------------------------------
const DIR_NAMES = ['front', 'left', 'back', 'right'];
const WALK_NAMES = ['stand', 'walkL', 'walkR'];
const HAIR_DIR_MAP = { front: 'front', left: 'left', back: 'back', right: 'right' };

// Agent role -> accessory template key
const ROLE_ACCESSORY = {
  planner: 'clipboard',
  coder: 'laptop',
  reviewer: 'magnifier',
  researcher: 'book',
  crm: 'card',
  support: 'wrench',
};

// ---------------------------------------------------------------------------
// Tactician sprite sheet — 384x32, 12 frames (4 dirs x 3 walk frames)
// ---------------------------------------------------------------------------
function generateTacticianSheet() {
  const width = 384;
  const height = 32;
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);

  const colorMap = buildColorMap(COLORS.tactician);

  for (let dir = 0; dir < 4; dir++) {
    for (let walk = 0; walk < 3; walk++) {
      const frameIndex = dir * 3 + walk;
      const ox = frameIndex * 32;

      const dirName = DIR_NAMES[dir];
      const walkName = WALK_NAMES[walk];
      const bodyKey = `${dirName}_${walkName}`;
      const bodyGrid = bodyTemplates[bodyKey];

      const layers = [bodyGrid];

      // Hair overlay (short style for tactician)
      const hairDir = HAIR_DIR_MAP[dirName];
      if (hairTemplates.short && hairTemplates.short[hairDir]) {
        layers.push(hairTemplates.short[hairDir]);
      }

      // Crown accessory
      if (accessories.player && accessories.player.crown) {
        layers.push(accessories.player.crown);
      }

      composeLayers(ctx, ox, 0, layers, colorMap);
    }
  }

  return { canvas, filename: 'tactician.png', dir: DIRS.sprites };
}

// ---------------------------------------------------------------------------
// Agent sprite sheets — 64x32, 2 frames (idle + working)
// ---------------------------------------------------------------------------
function generateAgentSheet(role, color) {
  const width = 64;
  const height = 32;
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);

  const colorMap = buildColorMap(color);

  // Frame 0: idle (front standing)
  const idleLayers = [bodyTemplates.front_stand];
  if (hairTemplates.short && hairTemplates.short.front) {
    idleLayers.push(hairTemplates.short.front);
  }
  composeLayers(ctx, 0, 0, idleLayers, colorMap);

  // Frame 1: working (right standing + role accessory)
  const workLayers = [bodyTemplates.right_stand];
  if (hairTemplates.short && hairTemplates.short.right) {
    workLayers.push(hairTemplates.short.right);
  }
  const accKey = ROLE_ACCESSORY[role];
  if (accKey && accessories.agent && accessories.agent[accKey]) {
    workLayers.push(accessories.agent[accKey]);
  }
  composeLayers(ctx, 32, 0, workLayers, colorMap);

  return { canvas, filename: `agent-${role}.png`, dir: DIRS.sprites };
}

// ---------------------------------------------------------------------------
// Office tileset — 256x32, 8 tiles at 32px each
// ---------------------------------------------------------------------------
function generateOfficeTileset() {
  const width = 256;
  const height = 32;
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);

  const tileOrder = [
    'floor', 'wall', 'desk',
    'dept_engineering', 'dept_sales', 'dept_support', 'dept_research',
    'review_station',
  ];

  for (let i = 0; i < tileOrder.length; i++) {
    const tileGrid = tileTemplates[tileOrder[i]];
    if (tileGrid) {
      renderPixelData(ctx, i * 32, 0, tileGrid, {});
    }
  }

  return { canvas, filename: 'office-tileset.png', dir: DIRS.tilesets };
}

// ---------------------------------------------------------------------------
// Emote spritesheet — 288x32, 9 frames
// ---------------------------------------------------------------------------
function generateEmoteSpritesheet() {
  const frameCount = 9;
  const width = frameCount * 32;
  const height = 32;
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);

  const emoteOrder = [
    'wave', 'thumbsup', 'heart', 'laugh', 'think',
    'clap', 'fire', 'sparkle', 'coffee',
  ];

  for (let i = 0; i < emoteOrder.length; i++) {
    const emoteGrid = emoteTemplates[emoteOrder[i]];
    if (emoteGrid) {
      renderPixelData(ctx, i * 32, 0, emoteGrid, {});
    }
  }

  return { canvas, filename: 'emotes.png', dir: DIRS.sprites };
}

// ---------------------------------------------------------------------------
// UI Icons — 4 separate 16x16 canvases
// ---------------------------------------------------------------------------
function generateIcon(name, filename) {
  const iconGrid = iconTemplates[name];
  if (!iconGrid) {
    console.warn(`  warning: no icon template for "${name}"`);
    return null;
  }
  const size = iconGrid[0].length;
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, size, size);
  renderPixelData(ctx, 0, 0, iconGrid, {});
  return { canvas, filename, dir: DIRS.ui };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  for (const dir of Object.values(DIRS)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const assets = [];

  // Tactician (12-frame walk sheet)
  assets.push(generateTacticianSheet());

  // Agent sprites
  const agents = [
    { role: 'planner', color: COLORS.planner },
    { role: 'coder', color: COLORS.coder },
    { role: 'reviewer', color: COLORS.reviewer },
    { role: 'researcher', color: COLORS.researcher },
    { role: 'crm', color: COLORS.crm },
    { role: 'support', color: COLORS.support },
  ];
  for (const agent of agents) {
    assets.push(generateAgentSheet(agent.role, agent.color));
  }

  // Office tileset
  assets.push(generateOfficeTileset());

  // Emote spritesheet
  assets.push(generateEmoteSpritesheet());

  // UI icons
  const iconDefs = [
    ['approve', 'icon-approve.png'],
    ['deny', 'icon-deny.png'],
    ['inspect', 'icon-inspect.png'],
    ['alert', 'icon-alert.png'],
  ];
  for (const [name, filename] of iconDefs) {
    const icon = generateIcon(name, filename);
    if (icon) assets.push(icon);
  }

  // Write all PNGs
  for (const { canvas, filename, dir } of assets) {
    const buffer = canvas.toBuffer('image/png');
    const filepath = path.join(dir, filename);
    fs.writeFileSync(filepath, buffer);
    console.log(`  wrote ${path.relative(process.cwd(), filepath)} (${buffer.length} bytes)`);
  }

  console.log(`\nGenerated ${assets.length} assets.`);
}

main().catch(console.error);
