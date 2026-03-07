import { describe, it, expect } from 'vitest';
import type { PixelGrid, SpriteTemplate } from '../sprite-data';
import { resolveColorMap, darken, lighten } from '../sprite-data';
import type { AvatarConfig } from '../avatar';
import bodyTemplates from '../sprite-data/body.json';
import hairTemplates from '../sprite-data/hair.json';
import accessoryTemplates from '../sprite-data/accessories.json';
import emoteTemplates from '../sprite-data/emotes.json';
import tileTemplates from '../sprite-data/tiles.json';
import iconTemplates from '../sprite-data/icons.json';

describe('PixelGrid type', () => {
  it('accepts a 2D array of strings and nulls', () => {
    const grid: PixelGrid = [
      ['S', null, 'O'],
      [null, 'C', null],
    ];
    expect(grid).toHaveLength(2);
    expect(grid[0]).toHaveLength(3);
  });
});

describe('SpriteTemplate type', () => {
  it('accepts width, height, and pixels', () => {
    const template: SpriteTemplate = {
      width: 32,
      height: 32,
      pixels: [['S']],
    };
    expect(template.width).toBe(32);
  });
});

describe('darken', () => {
  it('returns same color for factor 0', () => {
    expect(darken('#ffffff', 0)).toBe('#ffffff');
  });

  it('returns black for factor 1', () => {
    expect(darken('#ffffff', 1)).toBe('#000000');
  });

  it('darkens a color by the given factor', () => {
    const result = darken('#ff8000', 0.5);
    // R: 255*0.5=128=0x80, G: 128*0.5=64=0x40, B: 0*0.5=0=0x00
    expect(result).toBe('#804000');
  });
});

describe('lighten', () => {
  it('returns same color for factor 0', () => {
    expect(lighten('#808080', 0)).toBe('#808080');
  });

  it('returns white for factor 1', () => {
    expect(lighten('#000000', 1)).toBe('#ffffff');
  });

  it('lightens a color by the given factor', () => {
    const result = lighten('#000000', 0.5);
    // R: 0+(255-0)*0.5=128=0x80
    expect(result).toBe('#808080');
  });
});

describe('resolveColorMap', () => {
  it('maps palette tokens to hex colors based on avatar config', () => {
    const config: AvatarConfig = {
      skinTone: 0,
      hairStyle: 0,
      hairColor: 0,
      outfitColor: 0,
      accessory: -1,
    };
    const map = resolveColorMap(config);

    expect(map.S).toBe('#fcd5b0'); // SKIN_TONES[0]
    expect(map.H).toBe('#4a3728'); // HAIR_COLORS[0]
    expect(map.C).toBe('#6366f1'); // OUTFIT_COLORS[0]
    expect(map.O).toBe('#0f0f1a'); // outline
    expect(map.E).toBe('#0f0f1a'); // eye
    expect(map.W).toBe('#ffffff'); // white

    // Derived colors should be strings starting with #
    expect(map.D).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.L).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.X).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.K).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.B).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.P).toMatch(/^#[0-9a-f]{6}$/);
    expect(map.R).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('uses different skin tones based on config index', () => {
    const map0 = resolveColorMap({ skinTone: 0, hairStyle: 0, hairColor: 0, outfitColor: 0, accessory: -1 });
    const map1 = resolveColorMap({ skinTone: 1, hairStyle: 0, hairColor: 0, outfitColor: 0, accessory: -1 });
    expect(map0.S).not.toBe(map1.S);
  });

  it('uses different outfit colors based on config index', () => {
    const map0 = resolveColorMap({ skinTone: 0, hairStyle: 0, hairColor: 0, outfitColor: 0, accessory: -1 });
    const map2 = resolveColorMap({ skinTone: 0, hairStyle: 0, hairColor: 0, outfitColor: 2, accessory: -1 });
    expect(map0.C).not.toBe(map2.C);
  });
});

describe('body templates', () => {
  const expectedKeys = [
    'front_stand', 'front_walkL', 'front_walkR',
    'left_stand', 'left_walkL', 'left_walkR',
    'back_stand', 'back_walkL', 'back_walkR',
    'right_stand', 'right_walkL', 'right_walkR',
  ];

  it('contains all 12 direction/walk templates', () => {
    for (const key of expectedKeys) {
      expect(bodyTemplates).toHaveProperty(key);
    }
  });

  it('each template is a 32x32 grid', () => {
    for (const key of expectedKeys) {
      const grid = (bodyTemplates as unknown as Record<string, (string | null)[][]>)[key];
      expect(grid).toHaveLength(32);
      for (const row of grid) {
        expect(row).toHaveLength(32);
      }
    }
  });

  it('templates contain only valid tokens or null', () => {
    const validTokens = new Set(['S', 'O', 'H', 'C', 'D', 'L', 'E', 'W', 'X', 'G', 'K', 'B', 'P', 'R']);
    for (const key of expectedKeys) {
      const grid = (bodyTemplates as unknown as Record<string, (string | null)[][]>)[key];
      for (const row of grid) {
        for (const cell of row) {
          if (cell !== null) {
            expect(validTokens.has(cell)).toBe(true);
          }
        }
      }
    }
  });
});

describe('hair templates', () => {
  const styles = ['short', 'long', 'spiky', 'curly'];
  const directions = ['front', 'left', 'back', 'right'];

  it('contains all 4 styles with 4 directions each', () => {
    for (const style of styles) {
      expect(hairTemplates).toHaveProperty(style);
      for (const dir of directions) {
        expect((hairTemplates as Record<string, Record<string, unknown>>)[style]).toHaveProperty(dir);
      }
    }
  });

  it('each overlay is a 32x32 grid', () => {
    for (const style of styles) {
      for (const dir of directions) {
        const grid = (hairTemplates as Record<string, Record<string, (string | null)[][]>>)[style][dir];
        expect(grid).toHaveLength(32);
        for (const row of grid) {
          expect(row).toHaveLength(32);
        }
      }
    }
  });

  it('overlays only contain H tokens or null', () => {
    for (const style of styles) {
      for (const dir of directions) {
        const grid = (hairTemplates as Record<string, Record<string, (string | null)[][]>>)[style][dir];
        for (const row of grid) {
          for (const cell of row) {
            expect(cell === null || cell === 'H').toBe(true);
          }
        }
      }
    }
  });
});

describe('accessory templates', () => {
  it('has player accessories: glasses, crown, headphones, hat', () => {
    expect(accessoryTemplates.player).toHaveProperty('glasses');
    expect(accessoryTemplates.player).toHaveProperty('crown');
    expect(accessoryTemplates.player).toHaveProperty('headphones');
    expect(accessoryTemplates.player).toHaveProperty('hat');
  });

  it('has agent accessories: clipboard, laptop, magnifier, book, card, wrench', () => {
    expect(accessoryTemplates.agent).toHaveProperty('clipboard');
    expect(accessoryTemplates.agent).toHaveProperty('laptop');
    expect(accessoryTemplates.agent).toHaveProperty('magnifier');
    expect(accessoryTemplates.agent).toHaveProperty('book');
    expect(accessoryTemplates.agent).toHaveProperty('card');
    expect(accessoryTemplates.agent).toHaveProperty('wrench');
  });

  it('each accessory is a 32x32 grid', () => {
    const allAccessories = [
      ...Object.values(accessoryTemplates.player),
      ...Object.values(accessoryTemplates.agent),
    ];
    for (const grid of allAccessories) {
      expect(grid).toHaveLength(32);
      for (const row of grid as (string | null)[][]) {
        expect(row).toHaveLength(32);
      }
    }
  });
});

describe('emote templates', () => {
  const emoteNames = ['wave', 'thumbsup', 'heart', 'laugh', 'think', 'clap', 'fire', 'sparkle', 'coffee'];

  it('contains all 9 emotes', () => {
    for (const name of emoteNames) {
      expect(emoteTemplates).toHaveProperty(name);
    }
  });

  it('each emote is a 32x32 grid', () => {
    for (const name of emoteNames) {
      const grid = (emoteTemplates as Record<string, (string | null)[][]>)[name];
      expect(grid).toHaveLength(32);
      for (const row of grid) {
        expect(row).toHaveLength(32);
      }
    }
  });

  it('emotes use direct hex colors (not palette tokens)', () => {
    for (const name of emoteNames) {
      const grid = (emoteTemplates as Record<string, (string | null)[][]>)[name];
      for (const row of grid) {
        for (const cell of row) {
          if (cell !== null) {
            expect(cell).toMatch(/^#[0-9a-fA-F]{6}$/);
          }
        }
      }
    }
  });
});

describe('tile templates', () => {
  const tileNames = ['floor', 'wall', 'desk', 'dept_engineering', 'dept_sales', 'dept_support', 'dept_research', 'review_station'];

  it('contains all 8 tiles', () => {
    for (const name of tileNames) {
      expect(tileTemplates).toHaveProperty(name);
    }
  });

  it('each tile is a 32x32 grid', () => {
    for (const name of tileNames) {
      const grid = (tileTemplates as Record<string, (string | null)[][]>)[name];
      expect(grid).toHaveLength(32);
      for (const row of grid) {
        expect(row).toHaveLength(32);
      }
    }
  });
});

describe('icon templates', () => {
  const iconNames = ['approve', 'deny', 'inspect', 'alert'];

  it('contains all 4 icons', () => {
    for (const name of iconNames) {
      expect(iconTemplates).toHaveProperty(name);
    }
  });

  it('each icon is a 16x16 grid', () => {
    for (const name of iconNames) {
      const grid = (iconTemplates as Record<string, (string | null)[][]>)[name];
      expect(grid).toHaveLength(16);
      for (const row of grid) {
        expect(row).toHaveLength(16);
      }
    }
  });
});
