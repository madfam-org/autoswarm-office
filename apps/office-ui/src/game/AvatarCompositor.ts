import Phaser from 'phaser';
import type { AvatarConfig } from '@autoswarm/shared-types';
import { resolveColorMap } from '@autoswarm/shared-types';
import { composeLayers } from './sprite-data/renderer';
import bodyTemplates from '@autoswarm/shared-types/src/sprite-data/body.json';
import hairTemplates from '@autoswarm/shared-types/src/sprite-data/hair.json';
import accessoryTemplates from '@autoswarm/shared-types/src/sprite-data/accessories.json';

const HAIR_STYLE_KEYS = ['short', 'long', 'spiky', 'curly'] as const;

/**
 * Generates a unique texture key for a given avatar configuration.
 * Uses a hash of the config values to enable caching.
 */
export function avatarTextureKey(config: AvatarConfig): string {
  return `avatar-${config.skinTone}-${config.hairStyle}-${config.hairColor}-${config.outfitColor}-${config.accessory}`;
}

/**
 * Composites avatar layers into a single 32x32 canvas texture.
 * Uses pixel-data templates and shared renderer for consistent output.
 */
export function compositeAvatar(scene: Phaser.Scene, config: AvatarConfig): string {
  const key = avatarTextureKey(config);

  // Return cached if already exists
  if (scene.textures.exists(key)) {
    return key;
  }

  const canvas = scene.textures.createCanvas(key, 32, 32);
  if (!canvas) return 'tactician'; // fallback

  const ctx = canvas.getContext();
  ctx.clearRect(0, 0, 32, 32);

  const colorMap = resolveColorMap(config);

  // Build layer stack: body + hair + accessory
  const layers: ((string | null)[][] | null)[] = [
    bodyTemplates.front_stand,
  ];

  // Hair overlay
  if (config.hairStyle >= 0 && config.hairStyle < HAIR_STYLE_KEYS.length) {
    const styleKey = HAIR_STYLE_KEYS[config.hairStyle];
    const hairStyle = hairTemplates[styleKey];
    if (hairStyle?.front) {
      layers.push(hairStyle.front);
    }
  }

  // Accessory overlay
  const PLAYER_ACC_KEYS = ['glasses', 'crown', 'headphones', 'hat'] as const;
  if (config.accessory >= 0 && config.accessory < PLAYER_ACC_KEYS.length) {
    const accKey = PLAYER_ACC_KEYS[config.accessory];
    const accGrid = accessoryTemplates.player?.[accKey];
    if (accGrid) {
      layers.push(accGrid);
    }
  }

  composeLayers(ctx as unknown as CanvasRenderingContext2D, 0, 0, layers, colorMap);

  canvas.refresh();
  return key;
}
