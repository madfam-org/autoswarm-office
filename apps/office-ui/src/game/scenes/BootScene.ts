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

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' });
  }

  preload(): void {
    // Generate placeholder textures since we don't have real sprite assets yet.
    // Each texture is a colored rectangle rendered to a canvas texture.

    this.createRectTexture('tactician', SPRITE_SIZE, SPRITE_SIZE, COLORS.tactician);
    this.createRectTexture('agent-planner', SPRITE_SIZE, SPRITE_SIZE, COLORS.planner);
    this.createRectTexture('agent-coder', SPRITE_SIZE, SPRITE_SIZE, COLORS.coder);
    this.createRectTexture('agent-reviewer', SPRITE_SIZE, SPRITE_SIZE, COLORS.reviewer);
    this.createRectTexture('agent-researcher', SPRITE_SIZE, SPRITE_SIZE, COLORS.researcher);
    this.createRectTexture('agent-crm', SPRITE_SIZE, SPRITE_SIZE, COLORS.crm);
    this.createRectTexture('agent-support', SPRITE_SIZE, SPRITE_SIZE, COLORS.support);

    // Department zone overlays
    this.createRectTexture('zone-engineering', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptEngineering);
    this.createRectTexture('zone-sales', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptSales);
    this.createRectTexture('zone-support', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptSupport);
    this.createRectTexture('zone-research', TILE_SIZE * 6, TILE_SIZE * 5, COLORS.deptResearch);

    // UI icons
    this.createRectTexture('review-station', TILE_SIZE, TILE_SIZE, COLORS.reviewStation);
    this.createRectTexture('alert-icon', 16, 16, COLORS.alertIcon);

    // Floor tile
    this.createRectTexture('floor-tile', TILE_SIZE, TILE_SIZE, COLORS.floor);
    this.createRectTexture('wall-tile', TILE_SIZE, TILE_SIZE, COLORS.wall);
  }

  create(): void {
    this.scene.start('OfficeScene');
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
