import { describe, it, expect, vi } from 'vitest';
import { Pathfinder } from '../Pathfinder';

describe('Pathfinder', () => {
  it('returns direct path when no collision layer', () => {
    const pf = new Pathfinder(null, 1600, 896);
    const path = pf.findPath(100, 100, 500, 300);
    expect(path).toEqual([{ x: 500, y: 300 }]);
  });

  it('returns path with tile-center waypoints when collision layer exists', () => {
    // Mock collision layer with no blocked tiles
    const mockLayer = {
      getTileAt: vi.fn().mockReturnValue(null),
    } as unknown as Phaser.Tilemaps.TilemapLayer;

    const pf = new Pathfinder(mockLayer, 320, 320);
    const path = pf.findPath(48, 48, 144, 144);
    expect(path.length).toBeGreaterThan(0);
    // All waypoints should be tile-center aligned (multiples of 32 + 16)
    for (const wp of path) {
      expect(wp.x % 32).toBe(16);
      expect(wp.y % 32).toBe(16);
    }
  });

  it('returns direct path when destination is blocked', () => {
    const mockLayer = {
      getTileAt: vi.fn((x: number, y: number) => {
        // Block the destination tile (4, 4)
        if (x === 4 && y === 4) return { index: 1 };
        return null;
      }),
    } as unknown as Phaser.Tilemaps.TilemapLayer;

    const pf = new Pathfinder(mockLayer, 320, 320);
    const path = pf.findPath(16, 16, 144, 144);
    // Falls back to direct path since destination is blocked
    expect(path).toEqual([{ x: 144, y: 144 }]);
  });

  it('finds path around obstacles', () => {
    // Block a wall of tiles at x=3
    const mockLayer = {
      getTileAt: vi.fn((x: number, y: number) => {
        if (x === 3 && y >= 0 && y <= 3) return { index: 1 };
        return null;
      }),
    } as unknown as Phaser.Tilemaps.TilemapLayer;

    const pf = new Pathfinder(mockLayer, 320, 320);
    const path = pf.findPath(48, 48, 176, 48);
    expect(path.length).toBeGreaterThan(0);
    // Path should avoid column 3
    for (const wp of path) {
      const tileX = Math.floor((wp.x - 16) / 32);
      if (tileX === 3) {
        // If passing through column 3, y must be > 3*32+16 = 112
        expect(wp.y).toBeGreaterThan(112);
      }
    }
  });

  it('returns null-safe path when no route exists', () => {
    // Surround the start tile completely
    const mockLayer = {
      getTileAt: vi.fn((x: number, y: number) => {
        if (x === 0 && y === 0) return null; // Start tile is open
        return { index: 1 }; // Everything else blocked
      }),
    } as unknown as Phaser.Tilemaps.TilemapLayer;

    const pf = new Pathfinder(mockLayer, 320, 320);
    const path = pf.findPath(16, 16, 304, 304);
    // Should fall back to direct path when no route found
    expect(path).toEqual([{ x: 304, y: 304 }]);
  });

  it('handles same start and end position', () => {
    const pf = new Pathfinder(null, 1600, 896);
    const path = pf.findPath(100, 100, 100, 100);
    expect(path).toEqual([{ x: 100, y: 100 }]);
  });

  describe('findPathAdjacentTo', () => {
    it('returns direct path to the target when no collision layer', () => {
      const pf = new Pathfinder(null, 1600, 896);
      const path = pf.findPathAdjacentTo(100, 100, 500, 300);
      expect(path).toEqual([{ x: 500, y: 300 }]);
    });

    it('paths to a walkable neighbour tile, not the (occupied) target tile itself', () => {
      // Open grid — target tile (4,4) itself may be "occupied" by an avatar,
      // but the pathfinder only cares about collision, so any neighbour works.
      const mockLayer = {
        getTileAt: vi.fn().mockReturnValue(null),
      } as unknown as Phaser.Tilemaps.TilemapLayer;

      const pf = new Pathfinder(mockLayer, 320, 320);
      // Target at tile (4,4) -> world center (144, 144); start at tile (0,0).
      const path = pf.findPathAdjacentTo(16, 16, 144, 144);
      expect(path.length).toBeGreaterThan(0);
      const dest = path[path.length - 1];
      // Destination must be tile-center aligned and adjacent to (4,4), i.e.
      // NOT the target tile's own center.
      expect(dest.x % 32).toBe(16);
      expect(dest.y % 32).toBe(16);
      expect(dest).not.toEqual({ x: 144, y: 144 });
      const destTileX = (dest.x - 16) / 32;
      const destTileY = (dest.y - 16) / 32;
      const chebyshevDist = Math.max(Math.abs(destTileX - 4), Math.abs(destTileY - 4));
      expect(chebyshevDist).toBe(1);
    });

    it('prefers the neighbour tile closest to the start position', () => {
      const mockLayer = {
        getTileAt: vi.fn().mockReturnValue(null),
      } as unknown as Phaser.Tilemaps.TilemapLayer;

      const pf = new Pathfinder(mockLayer, 320, 320);
      // Start far to the east of the target (tile 4,4) -> nearest open
      // neighbour should be on the east side, tile (5,4).
      const path = pf.findPathAdjacentTo(304, 144, 144, 144);
      const dest = path[path.length - 1];
      const destTileX = (dest.x - 16) / 32;
      const destTileY = (dest.y - 16) / 32;
      expect(destTileX).toBe(5);
      expect(destTileY).toBe(4);
    });

    it('falls back to walking toward the target when every neighbour is blocked', () => {
      const mockLayer = {
        getTileAt: vi.fn((x: number, y: number) => {
          // Block all 8 neighbours of (4,4); leave (4,4) itself open.
          if (x === 4 && y === 4) return null;
          if (Math.abs(x - 4) <= 1 && Math.abs(y - 4) <= 1) return { index: 1 };
          return null;
        }),
      } as unknown as Phaser.Tilemaps.TilemapLayer;

      const pf = new Pathfinder(mockLayer, 320, 320);
      const path = pf.findPathAdjacentTo(16, 16, 144, 144);
      expect(path).toEqual([{ x: 144, y: 144 }]);
    });
  });
});
