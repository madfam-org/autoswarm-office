// CONVENTION: camelCase fields. Domain shape used by React + Phaser; the
// avatar config is persisted to localStorage and sent to Colyseus as a
// JSON string, so there is no Python wire-shape to mirror here.

/** Avatar customization configuration. */
export interface AvatarConfig {
  /** Skin tone index (0-3) */
  skinTone: number;
  /** Hair style index (0-3, or -1 for none) */
  hairStyle: number;
  /** Hair color index (0-3) */
  hairColor: number;
  /** Outfit color index (0-3) */
  outfitColor: number;
  /** Accessory index (0-3, or -1 for none) */
  accessory: number;
}

export const DEFAULT_AVATAR_CONFIG: AvatarConfig = {
  skinTone: 0,
  hairStyle: 0,
  hairColor: 0,
  outfitColor: 0,
  accessory: -1,
};

export const SKIN_TONES = ['#fcd5b0', '#d4a574', '#a67c52', '#6b4423'] as const;
export const HAIR_COLORS = ['#4a3728', '#d4a017', '#c0392b', '#2c3e50'] as const;
export const OUTFIT_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444'] as const;
export const HAIR_STYLE_NAMES = ['Short', 'Long', 'Spiky', 'Curly', 'Ponytail', 'Bob', 'Mohawk', 'Bun'] as const;
export const ACCESSORY_NAMES = ['None', 'Glasses', 'Crown', 'Headphones', 'Hat', 'Scarf', 'Backpack', 'Badge', 'Visor'] as const;
