import Phaser from 'phaser';

const TILE_SIZE = 32;
const SPRITE_SIZE = 32;
const COLORS = {
  tactician: 0x6366f1, // indigo
  planner: 0x8b5cf6, // violet
  coder: 0x06b6d4, // cyan
  reviewer: 0xf59e0b, // amber
  researcher: 0x10b981, // emerald
  crm: 0xf43f5e, // rose
  support: 0x0ea5e9, // sky
  floor: 0x1e293b, // slate-800
  wall: 0x334155, // slate-700
  deptEngineering: 0x1e3a5f,
  deptSales: 0x3b1e5f,
  deptSupport: 0x1e5f3a,
  deptResearch: 0x5f3a1e,
  reviewStation: 0xfbbf24, // gold
  alertIcon: 0xef4444, // red
};

const AGENT_ROLES = ['planner', 'coder', 'reviewer', 'researcher', 'crm', 'support'] as const;

export class BootScene extends Phaser.Scene {
  private failedKeys: Set<string> = new Set();

  constructor() {
    super({ key: 'BootScene' });
  }

  preload(): void {
    // Track failed loads so we can fall back to canvas-generated textures
    this.load.on('loaderror', (fileObj: Phaser.Loader.File) => {
      this.failedKeys.add(fileObj.key);
    });

    // Spritesheets
    this.load.spritesheet('tactician', '/assets/sprites/tactician.png', {
      frameWidth: 32,
      frameHeight: 32,
    });
    for (const role of AGENT_ROLES) {
      this.load.spritesheet(`agent-${role}`, `/assets/sprites/agent-${role}.png`, {
        frameWidth: 32,
        frameHeight: 32,
      });
    }

    // Tileset
    this.load.spritesheet('office-tileset', '/assets/tilesets/office-tileset.png', {
      frameWidth: 32,
      frameHeight: 32,
    });

    // Tiled map (optional — graceful fallback if missing)
    this.load.tilemapTiledJSON('office-map', '/assets/maps/office-default.tmj');
    this.load.image('office-tiles', '/assets/tilesets/office-tileset.png');

    // UI icons
    this.load.image('icon-approve', '/assets/ui/icon-approve.png');
    this.load.image('icon-deny', '/assets/ui/icon-deny.png');
    this.load.image('icon-inspect', '/assets/ui/icon-inspect.png');
    this.load.image('icon-alert', '/assets/ui/icon-alert.png');
  }

  create(): void {
    // Generate canvas fallbacks for any textures that failed to load from files
    this.generateFallbacks();

    // Department zone overlays are always canvas-generated (variable-size)
    this.createRectTexture('zone-engineering', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptEngineering);
    this.createRectTexture('zone-sales', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptSales);
    this.createRectTexture('zone-support', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptSupport);
    this.createRectTexture('zone-research', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptResearch);

    // Floor and wall tiles — fallback only if file load failed
    if (this.failedKeys.has('office-tileset')) {
      this.createRectTexture('floor-tile', TILE_SIZE, TILE_SIZE, COLORS.floor);
      this.createRectTexture('wall-tile', TILE_SIZE, TILE_SIZE, COLORS.wall);
      this.createRectTexture('review-station', TILE_SIZE, TILE_SIZE, COLORS.reviewStation);
    }

    this.scene.start('OfficeScene');
  }

  private generateFallbacks(): void {
    // Tactician fallback
    if (this.failedKeys.has('tactician')) {
      this.createRectTexture('tactician', SPRITE_SIZE, SPRITE_SIZE, COLORS.tactician);
    }

    // Agent fallbacks
    for (const role of AGENT_ROLES) {
      const key = `agent-${role}`;
      if (this.failedKeys.has(key)) {
        this.createRectTexture(key, SPRITE_SIZE, SPRITE_SIZE, COLORS[role]);
      }
    }

    // UI icon fallbacks
    if (this.failedKeys.has('icon-alert')) {
      this.createRectTexture('icon-alert', 16, 16, COLORS.alertIcon);
    }
    if (this.failedKeys.has('icon-approve')) {
      this.createRectTexture('icon-approve', 16, 16, 0x10b981);
    }
    if (this.failedKeys.has('icon-deny')) {
      this.createRectTexture('icon-deny', 16, 16, 0xef4444);
    }
    if (this.failedKeys.has('icon-inspect')) {
      this.createRectTexture('icon-inspect', 16, 16, 0x06b6d4);
    }
  }

  private createRectTexture(
    key: string,
    width: number,
    height: number,
    color: number,
  ): void {
    const canvas = this.textures.createCanvas(key, width, height);
    if (!canvas) return;

    const ctx = canvas.getContext();
    const r = (color >> 16) & 0xff;
    const g = (color >> 8) & 0xff;
    const b = color & 0xff;

    // Fill with main color
    ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
    ctx.fillRect(0, 0, width, height);

    // Pixel-art border: 2px dark border on all sides
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, width - 2, height - 2);

    // Highlight on top-left edges for 3D pixel effect
    ctx.strokeStyle = `rgba(255, 255, 255, 0.2)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(2, height - 2);
    ctx.lineTo(2, 2);
    ctx.lineTo(width - 2, 2);
    ctx.stroke();

    canvas.refresh();
  }
}
