/**
 * generate-assets.js
 *
 * Programmatically draws pixel-art sprites and tilesets using @napi-rs/canvas,
 * then writes them as PNGs into apps/office-ui/public/assets/.
 *
 * Usage:  node scripts/generate-assets.js
 */

const { createCanvas } = require('@napi-rs/canvas');
const fs = require('node:fs');
const path = require('node:path');

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
  floor: '#1e293b',
  wall: '#334155',
  deptEngineering: '#1e3a5f',
  deptSales: '#3b1e5f',
  deptSupport: '#1e5f3a',
  deptResearch: '#5f3a1e',
  reviewStation: '#fbbf24',
};

const OUTLINE = '#0f0f1a';

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
// Helpers
// ---------------------------------------------------------------------------

/** Fill a rectangle with a solid color. */
function drawPixelRect(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

/** Draw a 1px dark outline around a rectangle. */
function drawOutline(ctx, x, y, w, h) {
  ctx.strokeStyle = OUTLINE;
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
}

/**
 * Darken a hex color by a factor (0-1, where 0 = same, 1 = black).
 */
function darken(hex, factor) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const dr = Math.round(r * (1 - factor));
  const dg = Math.round(g * (1 - factor));
  const db = Math.round(b * (1 - factor));
  return `rgb(${dr},${dg},${db})`;
}

/**
 * Lighten a hex color by a factor (0-1, where 0 = same, 1 = white).
 */
function lighten(hex, factor) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lr = Math.round(r + (255 - r) * factor);
  const lg = Math.round(g + (255 - g) * factor);
  const lb = Math.round(b + (255 - b) * factor);
  return `rgb(${lr},${lg},${lb})`;
}

/**
 * Draw a humanoid pixel-art character within a 32x32 cell.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} ox - left edge of the 32x32 cell
 * @param {number} oy - top edge of the 32x32 cell
 * @param {string} color - primary hex color
 * @param {object} opts
 * @param {number} opts.legOffsetL - left leg x-shift (for walk frames)
 * @param {number} opts.legOffsetR - right leg x-shift
 * @param {number} opts.bodyShiftX - body horizontal shift (facing direction)
 * @param {boolean} opts.facingRight - flip indicator
 */
function drawCharacter(ctx, ox, oy, color, opts = {}) {
  const {
    legOffsetL = 0,
    legOffsetR = 0,
    bodyShiftX = 0,
  } = opts;

  const bodyColor = darken(color, 0.15);
  const skinColor = '#fcd5b0';

  // Center the character within the 32x32 cell
  const cx = ox + 12 + bodyShiftX; // left edge of the 8px-wide head
  const cy = oy + 4;               // top of head

  // Head: 8x8
  drawPixelRect(ctx, cx, cy, 8, 8, skinColor);
  drawOutline(ctx, cx, cy, 8, 8);

  // Eyes (2 pixels)
  drawPixelRect(ctx, cx + 2, cy + 3, 2, 2, OUTLINE);
  drawPixelRect(ctx, cx + 5, cy + 3, 2, 2, OUTLINE);

  // Body: 8x12
  drawPixelRect(ctx, cx, cy + 8, 8, 12, bodyColor);
  drawOutline(ctx, cx, cy + 8, 8, 12);

  // Shirt color accent (upper body area)
  drawPixelRect(ctx, cx + 1, cy + 9, 6, 5, color);

  // Legs: 2x 4x4 blocks
  const legY = cy + 20;
  // Left leg
  drawPixelRect(ctx, cx + legOffsetL, legY, 4, 4, darken(color, 0.3));
  drawOutline(ctx, cx + legOffsetL, legY, 4, 4);
  // Right leg
  drawPixelRect(ctx, cx + 4 + legOffsetR, legY, 4, 4, darken(color, 0.3));
  drawOutline(ctx, cx + 4 + legOffsetR, legY, 4, 4);

  // Return head position for accessories
  return { headX: cx, headY: cy, bodyX: cx, bodyY: cy + 8 };
}

// ---------------------------------------------------------------------------
// Accessory drawers (one per agent role)
// ---------------------------------------------------------------------------

function drawAccessoryPlanner(ctx, pos) {
  // Clipboard: small rect to the right of the body
  drawPixelRect(ctx, pos.bodyX + 9, pos.bodyY + 2, 4, 6, '#d4a574');
  drawOutline(ctx, pos.bodyX + 9, pos.bodyY + 2, 4, 6);
  // Paper on clipboard
  drawPixelRect(ctx, pos.bodyX + 10, pos.bodyY + 3, 2, 4, '#ffffff');
}

function drawAccessoryCoder(ctx, pos) {
  // Laptop: rect in front at waist level
  drawPixelRect(ctx, pos.bodyX - 3, pos.bodyY + 6, 6, 4, '#374151');
  drawOutline(ctx, pos.bodyX - 3, pos.bodyY + 6, 6, 4);
  // Screen glow
  drawPixelRect(ctx, pos.bodyX - 2, pos.bodyY + 7, 4, 2, '#67e8f9');
}

function drawAccessoryReviewer(ctx, pos) {
  // Magnifying glass: circle + handle near hand
  const mx = pos.bodyX + 9;
  const my = pos.bodyY + 4;
  ctx.strokeStyle = '#78716c';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(mx + 2, my + 2, 3, 0, Math.PI * 2);
  ctx.stroke();
  // Handle
  ctx.beginPath();
  ctx.moveTo(mx + 4, my + 4);
  ctx.lineTo(mx + 7, my + 7);
  ctx.stroke();
}

function drawAccessoryResearcher(ctx, pos) {
  // Book: rect at side
  drawPixelRect(ctx, pos.bodyX + 9, pos.bodyY + 3, 5, 6, '#065f46');
  drawOutline(ctx, pos.bodyX + 9, pos.bodyY + 3, 5, 6);
  // Pages
  drawPixelRect(ctx, pos.bodyX + 10, pos.bodyY + 4, 3, 4, '#ecfdf5');
}

function drawAccessoryCRM(ctx, pos) {
  // Card: small rect held out
  drawPixelRect(ctx, pos.bodyX + 9, pos.bodyY + 4, 5, 3, '#ffffff');
  drawOutline(ctx, pos.bodyX + 9, pos.bodyY + 4, 5, 3);
  // Text line on card
  drawPixelRect(ctx, pos.bodyX + 10, pos.bodyY + 5, 3, 1, '#9ca3af');
}

function drawAccessorySupport(ctx, pos) {
  // Wrench: angled line with head
  ctx.strokeStyle = '#9ca3af';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pos.bodyX + 9, pos.bodyY + 8);
  ctx.lineTo(pos.bodyX + 13, pos.bodyY + 3);
  ctx.stroke();
  // Wrench head (small open circle)
  ctx.strokeStyle = '#9ca3af';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(pos.bodyX + 13, pos.bodyY + 2, 2, 0, Math.PI * 2);
  ctx.stroke();
}

const ACCESSORY_DRAWERS = {
  planner: drawAccessoryPlanner,
  coder: drawAccessoryCoder,
  reviewer: drawAccessoryReviewer,
  researcher: drawAccessoryResearcher,
  crm: drawAccessoryCRM,
  support: drawAccessorySupport,
};

// ---------------------------------------------------------------------------
// Tactician sprite sheet — 384x32, 12 frames (4 dirs x 3 walk frames)
// ---------------------------------------------------------------------------

function generateTacticianSheet() {
  const width = 384;
  const height = 32;
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');

  // Transparent background
  ctx.clearRect(0, 0, width, height);

  const color = COLORS.tactician;

  // Directions: 0=down, 1=left, 2=up, 3=right
  // Walk frames: 0=standing, 1=left-step, 2=right-step
  const walkLegOffsets = [
    { legOffsetL: 0, legOffsetR: 0 },   // standing
    { legOffsetL: -1, legOffsetR: 1 },   // left-step
    { legOffsetL: 1, legOffsetR: -1 },   // right-step
  ];

  const dirBodyShifts = [
    { bodyShiftX: 0 },   // down
    { bodyShiftX: -1 },  // left
    { bodyShiftX: 0 },   // up
    { bodyShiftX: 1 },   // right
  ];

  for (let dir = 0; dir < 4; dir++) {
    for (let walk = 0; walk < 3; walk++) {
      const frameIndex = dir * 3 + walk;
      const ox = frameIndex * 32;

      const opts = {
        ...walkLegOffsets[walk],
        ...dirBodyShifts[dir],
      };

      const pos = drawCharacter(ctx, ox, 0, color, opts);

      // Crown/hat indicator on the tactician's head
      const crownColor = '#fbbf24';
      // Crown base
      drawPixelRect(ctx, pos.headX + 1, pos.headY - 3, 6, 2, crownColor);
      // Crown points (3 small triangular peaks)
      drawPixelRect(ctx, pos.headX + 1, pos.headY - 4, 2, 1, crownColor);
      drawPixelRect(ctx, pos.headX + 3, pos.headY - 5, 2, 2, crownColor);
      drawPixelRect(ctx, pos.headX + 5, pos.headY - 4, 2, 1, crownColor);
      // Crown gem
      drawPixelRect(ctx, pos.headX + 3, pos.headY - 4, 2, 1, '#ef4444');

      // For "up" direction (dir=2), don't draw eyes (facing away)
      if (dir === 2) {
        // Cover eyes with skin color
        drawPixelRect(ctx, pos.headX + 2, pos.headY + 3, 2, 2, '#fcd5b0');
        drawPixelRect(ctx, pos.headX + 5, pos.headY + 3, 2, 2, '#fcd5b0');
        // Draw hair/back of head detail
        drawPixelRect(ctx, pos.headX + 1, pos.headY + 1, 6, 3, darken(color, 0.1));
      }
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

  // Frame 0: idle (standing, no accessory emphasis)
  const posIdle = drawCharacter(ctx, 0, 0, color);

  // Frame 1: working (slight pose change + accessory)
  const posWork = drawCharacter(ctx, 32, 0, color, { bodyShiftX: 1 });

  // Draw the role-specific accessory on the working frame
  const drawAccessory = ACCESSORY_DRAWERS[role];
  if (drawAccessory) {
    drawAccessory(ctx, posWork);
  }

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

  // Tile 0: Floor (dark with subtle grid lines)
  {
    const ox = 0;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.floor);
    ctx.strokeStyle = lighten(COLORS.floor, 0.08);
    ctx.lineWidth = 1;
    // Horizontal grid lines
    for (let y = 8; y < 32; y += 8) {
      ctx.beginPath();
      ctx.moveTo(ox, y + 0.5);
      ctx.lineTo(ox + 32, y + 0.5);
      ctx.stroke();
    }
    // Vertical grid lines
    for (let x = 8; x < 32; x += 8) {
      ctx.beginPath();
      ctx.moveTo(ox + x + 0.5, 0);
      ctx.lineTo(ox + x + 0.5, 32);
      ctx.stroke();
    }
  }

  // Tile 1: Wall (darker with brick pattern)
  {
    const ox = 32;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.wall);
    ctx.strokeStyle = darken(COLORS.wall, 0.2);
    ctx.lineWidth = 1;
    // Brick rows
    for (let row = 0; row < 4; row++) {
      const y = row * 8;
      // Horizontal mortar line
      ctx.beginPath();
      ctx.moveTo(ox, y + 0.5);
      ctx.lineTo(ox + 32, y + 0.5);
      ctx.stroke();
      // Vertical mortar lines (offset every other row)
      const offset = (row % 2 === 0) ? 0 : 8;
      for (let x = offset; x < 32; x += 16) {
        ctx.beginPath();
        ctx.moveTo(ox + x + 0.5, y);
        ctx.lineTo(ox + x + 0.5, y + 8);
        ctx.stroke();
      }
    }
    drawOutline(ctx, ox, 0, 32, 32);
  }

  // Tile 2: Desk (brown rectangle)
  {
    const ox = 64;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.floor); // floor underneath
    // Desk top surface
    drawPixelRect(ctx, ox + 2, 4, 28, 18, '#8b6914');
    drawOutline(ctx, ox + 2, 4, 28, 18);
    // Desk surface highlight
    drawPixelRect(ctx, ox + 3, 5, 26, 2, lighten('#8b6914', 0.2));
    // Desk legs
    drawPixelRect(ctx, ox + 4, 22, 3, 8, '#6b4f10');
    drawPixelRect(ctx, ox + 25, 22, 3, 8, '#6b4f10');
  }

  // Tile 3: Dept zone — Engineering
  {
    const ox = 96;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.deptEngineering);
    // Subtle circuit-like pattern
    ctx.strokeStyle = lighten(COLORS.deptEngineering, 0.12);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(ox + 4, 16);
    ctx.lineTo(ox + 16, 16);
    ctx.lineTo(ox + 16, 8);
    ctx.lineTo(ox + 28, 8);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(ox + 8, 24);
    ctx.lineTo(ox + 20, 24);
    ctx.lineTo(ox + 20, 28);
    ctx.stroke();
    drawOutline(ctx, ox, 0, 32, 32);
  }

  // Tile 4: Dept zone — Sales
  {
    const ox = 128;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.deptSales);
    // Small dollar sign pattern
    ctx.strokeStyle = lighten(COLORS.deptSales, 0.12);
    ctx.lineWidth = 1;
    // Diagonal accent lines
    for (let i = 0; i < 3; i++) {
      ctx.beginPath();
      ctx.moveTo(ox + 4 + i * 10, 4);
      ctx.lineTo(ox + 10 + i * 10, 28);
      ctx.stroke();
    }
    drawOutline(ctx, ox, 0, 32, 32);
  }

  // Tile 5: Dept zone — Support
  {
    const ox = 160;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.deptSupport);
    // Cross/plus patterns (support theme)
    ctx.strokeStyle = lighten(COLORS.deptSupport, 0.12);
    ctx.lineWidth = 1;
    // Small plus at center
    ctx.beginPath();
    ctx.moveTo(ox + 16, 10);
    ctx.lineTo(ox + 16, 22);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(ox + 10, 16);
    ctx.lineTo(ox + 22, 16);
    ctx.stroke();
    drawOutline(ctx, ox, 0, 32, 32);
  }

  // Tile 6: Dept zone — Research
  {
    const ox = 192;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.deptResearch);
    // Atom-like circle pattern
    ctx.strokeStyle = lighten(COLORS.deptResearch, 0.12);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(ox + 16, 16, 8, 0, Math.PI * 2);
    ctx.stroke();
    // Small dot in center
    drawPixelRect(ctx, ox + 15, 15, 2, 2, lighten(COLORS.deptResearch, 0.2));
    drawOutline(ctx, ox, 0, 32, 32);
  }

  // Tile 7: Review station (gold with star)
  {
    const ox = 224;
    drawPixelRect(ctx, ox, 0, 32, 32, COLORS.reviewStation);
    drawOutline(ctx, ox, 0, 32, 32);
    // Draw a 5-pointed star in the center
    const starColor = '#ffffff';
    ctx.fillStyle = starColor;
    ctx.beginPath();
    const scx = ox + 16;
    const scy = 16;
    const outerR = 8;
    const innerR = 4;
    for (let i = 0; i < 5; i++) {
      // Outer point
      const outerAngle = (Math.PI / 2) + (i * 2 * Math.PI / 5);
      const outerX = scx + outerR * Math.cos(outerAngle);
      const outerY = scy - outerR * Math.sin(outerAngle);
      if (i === 0) ctx.moveTo(outerX, outerY);
      else ctx.lineTo(outerX, outerY);
      // Inner point
      const innerAngle = outerAngle + Math.PI / 5;
      const innerX = scx + innerR * Math.cos(innerAngle);
      const innerY = scy - innerR * Math.sin(innerAngle);
      ctx.lineTo(innerX, innerY);
    }
    ctx.closePath();
    ctx.fill();
    // Star outline
    ctx.strokeStyle = darken(COLORS.reviewStation, 0.3);
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  return { canvas, filename: 'office-tileset.png', dir: DIRS.tilesets };
}

// ---------------------------------------------------------------------------
// UI Icons — 4 separate 16x16 canvases
// ---------------------------------------------------------------------------

function generateIconApprove() {
  const canvas = createCanvas(16, 16);
  const ctx = canvas.getContext('2d');

  // Green background
  drawPixelRect(ctx, 0, 0, 16, 16, '#22c55e');
  drawOutline(ctx, 0, 0, 16, 16);

  // White checkmark: two lines forming a check
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(3, 8);
  ctx.lineTo(6, 12);
  ctx.lineTo(13, 4);
  ctx.stroke();

  return { canvas, filename: 'icon-approve.png', dir: DIRS.ui };
}

function generateIconDeny() {
  const canvas = createCanvas(16, 16);
  const ctx = canvas.getContext('2d');

  // Red background
  drawPixelRect(ctx, 0, 0, 16, 16, '#ef4444');
  drawOutline(ctx, 0, 0, 16, 16);

  // White X: two diagonal lines
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(4, 4);
  ctx.lineTo(12, 12);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(12, 4);
  ctx.lineTo(4, 12);
  ctx.stroke();

  return { canvas, filename: 'icon-deny.png', dir: DIRS.ui };
}

function generateIconInspect() {
  const canvas = createCanvas(16, 16);
  const ctx = canvas.getContext('2d');

  // Transparent background
  ctx.clearRect(0, 0, 16, 16);

  // Magnifying glass: circle + handle
  ctx.strokeStyle = '#06b6d4'; // cyan
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(7, 7, 5, 0, Math.PI * 2);
  ctx.stroke();

  // Handle
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(11, 11);
  ctx.lineTo(14, 14);
  ctx.stroke();

  // Lens highlight
  ctx.strokeStyle = lighten('#06b6d4', 0.4);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(6, 5, 2, Math.PI * 0.8, Math.PI * 1.6);
  ctx.stroke();

  return { canvas, filename: 'icon-inspect.png', dir: DIRS.ui };
}

function generateIconAlert() {
  const canvas = createCanvas(16, 16);
  const ctx = canvas.getContext('2d');

  // Transparent background
  ctx.clearRect(0, 0, 16, 16);

  // Red triangle
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.moveTo(8, 1);
  ctx.lineTo(15, 14);
  ctx.lineTo(1, 14);
  ctx.closePath();
  ctx.fill();

  // Triangle outline
  ctx.strokeStyle = darken('#ef4444', 0.3);
  ctx.lineWidth = 1;
  ctx.stroke();

  // White exclamation mark
  ctx.fillStyle = '#ffffff';
  // Exclamation body
  drawPixelRect(ctx, 7, 4, 2, 6, '#ffffff');
  // Exclamation dot
  drawPixelRect(ctx, 7, 11, 2, 2, '#ffffff');

  return { canvas, filename: 'icon-alert.png', dir: DIRS.ui };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  // Create output directories
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

  // UI icons
  assets.push(generateIconApprove());
  assets.push(generateIconDeny());
  assets.push(generateIconInspect());
  assets.push(generateIconAlert());

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
