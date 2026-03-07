import type { AvatarConfig } from '../avatar';
import { SKIN_TONES, HAIR_COLORS, OUTFIT_COLORS } from '../avatar';

/**
 * Darken a hex color by a factor (0 = same, 1 = black).
 */
export function darken(hex: string, factor: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const dr = Math.round(r * (1 - factor));
  const dg = Math.round(g * (1 - factor));
  const db = Math.round(b * (1 - factor));
  return `#${dr.toString(16).padStart(2, '0')}${dg.toString(16).padStart(2, '0')}${db.toString(16).padStart(2, '0')}`;
}

/**
 * Lighten a hex color by a factor (0 = same, 1 = white).
 */
export function lighten(hex: string, factor: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lr = Math.round(r + (255 - r) * factor);
  const lg = Math.round(g + (255 - g) * factor);
  const lb = Math.round(b + (255 - b) * factor);
  return `#${lr.toString(16).padStart(2, '0')}${lg.toString(16).padStart(2, '0')}${lb.toString(16).padStart(2, '0')}`;
}

/**
 * Resolve palette tokens to actual hex colors based on avatar config.
 */
export function resolveColorMap(config: AvatarConfig): Record<string, string> {
  const skin = SKIN_TONES[config.skinTone] ?? SKIN_TONES[0];
  const hair = HAIR_COLORS[config.hairColor] ?? HAIR_COLORS[0];
  const outfit = OUTFIT_COLORS[config.outfitColor] ?? OUTFIT_COLORS[0];

  return {
    S: skin,
    K: darken(skin, 0.15),
    O: '#0f0f1a',
    H: hair,
    C: outfit,
    D: darken(outfit, 0.15),
    L: lighten(outfit, 0.2),
    E: '#0f0f1a',
    W: '#ffffff',
    X: darken(outfit, 0.3),
    G: lighten(outfit, 0.3),
    B: darken(outfit, 0.25),
    P: darken(outfit, 0.3),
    R: darken(outfit, 0.4),
  };
}

/**
 * Resolve a color map for a fixed-color role (agent, not customizable).
 * Uses the role color as the outfit.
 */
export function resolveRoleColorMap(roleColor: string): Record<string, string> {
  const skin = '#fcd5b0';
  return {
    S: skin,
    K: darken(skin, 0.15),
    O: '#0f0f1a',
    H: '#4a3728',
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
