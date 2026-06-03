import Phaser from 'phaser';
import type { AvatarConfig } from '@selva/shared-types';
import { resolveColorMap } from '@selva/shared-types';
import { composeLayers } from './sprite-data/renderer';
import bodyTemplates from '@selva/shared-types/src/sprite-data/body.json';
import hairTemplates from '@selva/shared-types/src/sprite-data/hair.json';
import accessoryTemplates from '@selva/shared-types/src/sprite-data/accessories.json';

const HAIR_STYLE_KEYS = ['short', 'long', 'spiky', 'curly', 'ponytail', 'bob', 'mohawk', 'bun'] as const;

/**
 * Frame layout for the 384x32 spritesheet (12 frames, 32px each):
 *   0  front_stand    (down idle)
 *   1  front_walkL    (down walk 1)
 *   2  front_walkR    (down walk 2)
 *   3  left_stand     (left idle)
 *   4  left_walkL     (left walk 1)
 *   5  left_walkR     (left walk 2)
 *   6  back_stand     (up idle)
 *   7  back_walkL     (up walk 1)
 *   8  back_walkR     (up walk 2)
 *   9  right_stand    (right idle)
 *  10  right_walkL    (right walk 1)
 *  11  right_walkR    (right walk 2)
 */
const FRAME_DEFS: { bodyKey: string; hairDir: string }[] = [
  { bodyKey: 'front_stand', hairDir: 'front' },
  { bodyKey: 'front_walkL', hairDir: 'front' },
  { bodyKey: 'front_walkR', hairDir: 'front' },
  { bodyKey: 'left_stand',  hairDir: 'left' },
  { bodyKey: 'left_walkL',  hairDir: 'left' },
  { bodyKey: 'left_walkR',  hairDir: 'left' },
  { bodyKey: 'back_stand',  hairDir: 'back' },
  { bodyKey: 'back_walkL',  hairDir: 'back' },
  { bodyKey: 'back_walkR',  hairDir: 'back' },
  { bodyKey: 'right_stand', hairDir: 'right' },
  { bodyKey: 'right_walkL', hairDir: 'right' },
  { bodyKey: 'right_walkR', hairDir: 'right' },
];

const FRAME_COUNT = FRAME_DEFS.length; // 12
const SHEET_WIDTH = FRAME_COUNT * 32;  // 384
const SHEET_HEIGHT = 32;

/**
 * Generates a unique texture key for a given avatar configuration.
 * Uses a hash of the config values to enable caching.
 */
export function avatarTextureKey(config: AvatarConfig): string {
  return `avatar-${config.skinTone}-${config.hairStyle}-${config.hairColor}-${config.outfitColor}-${config.accessory}`;
}

/**
 * Composites avatar layers into a 384x32 spritesheet (12 frames)
 * with 4 directional poses x 3 walk cycle frames.
 * Returns the texture key. Phaser spritesheet frames are registered
 * so that the texture can be used with animations.
 */
export function compositeAvatar(scene: Phaser.Scene, config: AvatarConfig): string {
  const key = avatarTextureKey(config);

  // Return cached if already exists
  if (scene.textures.exists(key)) {
    return key;
  }

  const canvas = scene.textures.createCanvas(key, SHEET_WIDTH, SHEET_HEIGHT);
  if (!canvas) return 'tactician'; // fallback

  const ctx = canvas.getContext();
  ctx.clearRect(0, 0, SHEET_WIDTH, SHEET_HEIGHT);

  const colorMap = resolveColorMap(config);

  // Player accessory (only applied on front-facing frames)
  const PLAYER_ACC_KEYS = ['glasses', 'crown', 'headphones', 'hat', 'scarf', 'backpack', 'badge', 'visor'] as const;
  let accGrid: (string | null)[][] | null = null;
  if (config.accessory >= 0 && config.accessory < PLAYER_ACC_KEYS.length) {
    const accKey = PLAYER_ACC_KEYS[config.accessory];
    accGrid = (accessoryTemplates.player as Record<string, (string | null)[][]>)?.[accKey] ?? null;
  }

  for (let i = 0; i < FRAME_COUNT; i++) {
    const def = FRAME_DEFS[i];
    const ox = i * 32;

    // Body layer
    const bodyGrid = (bodyTemplates as Record<string, (string | null)[][]>)[def.bodyKey];
    const layers: ((string | null)[][] | null)[] = [bodyGrid];

    // Hair overlay (directional)
    if (config.hairStyle >= 0 && config.hairStyle < HAIR_STYLE_KEYS.length) {
      const styleKey = HAIR_STYLE_KEYS[config.hairStyle];
      const hairStyle = (hairTemplates as Record<string, Record<string, (string | null)[][]>>)[styleKey];
      if (hairStyle?.[def.hairDir]) {
        layers.push(hairStyle[def.hairDir]);
      }
    }

    // Accessories only on front-facing frames (indices 0-2) since they are front-only grids
    if (accGrid && def.hairDir === 'front') {
      layers.push(accGrid);
    }

    composeLayers(ctx as unknown as CanvasRenderingContext2D, ox, 0, layers, colorMap);
  }

  canvas.refresh();

  // Register spritesheet frames on the texture so Phaser can index them
  const texture = scene.textures.get(key);
  if (texture) {
    // Remove the default frame 0 that covers the entire canvas
    // and add individual 32x32 frames
    for (let i = 0; i < FRAME_COUNT; i++) {
      texture.add(i, 0, i * 32, 0, 32, 32);
    }
  }

  return key;
}

/**
 * Create walk and idle animations for a given avatar texture key.
 * Animation keys follow the pattern: `{textureKey}-walk-{dir}` and
 * `{textureKey}-idle-{dir}`. Safe to call multiple times for the same
 * key -- duplicate calls are no-ops.
 */
export function createAvatarAnimations(scene: Phaser.Scene, textureKey: string): void {
  const directions = ['down', 'left', 'up', 'right'] as const;

  for (let dirIndex = 0; dirIndex < directions.length; dirIndex++) {
    const dir = directions[dirIndex];
    const startFrame = dirIndex * 3;

    const walkKey = `${textureKey}-walk-${dir}`;
    if (!scene.anims.exists(walkKey)) {
      scene.anims.create({
        key: walkKey,
        frames: [
          { key: textureKey, frame: startFrame },
          { key: textureKey, frame: startFrame + 1 },
          { key: textureKey, frame: startFrame },
          { key: textureKey, frame: startFrame + 2 },
        ],
        frameRate: 8,
        repeat: -1,
      });
    }

    const idleKey = `${textureKey}-idle-${dir}`;
    if (!scene.anims.exists(idleKey)) {
      scene.anims.create({
        key: idleKey,
        frames: [{ key: textureKey, frame: startFrame }],
        frameRate: 1,
        repeat: 0,
      });
    }
  }
}
