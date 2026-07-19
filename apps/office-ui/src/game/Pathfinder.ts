import Phaser from 'phaser';
import { TILE_SIZE } from './constants';

interface PathNode {
  x: number;
  y: number;
  g: number;
  h: number;
  f: number;
  parent: PathNode | null;
}

/**
 * Simple A* pathfinder on the collision grid.
 * Falls back to direct walk if no collision layer.
 */
export class Pathfinder {
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null;
  private worldWidth: number;
  private worldHeight: number;

  constructor(
    collisionLayer: Phaser.Tilemaps.TilemapLayer | null,
    worldWidth: number,
    worldHeight: number,
  ) {
    this.collisionLayer = collisionLayer;
    this.worldWidth = worldWidth;
    this.worldHeight = worldHeight;
  }

  /**
   * Find path from start to end in world coordinates.
   * Returns array of world-coordinate waypoints, or direct line if no collision layer.
   */
  findPath(
    startX: number,
    startY: number,
    endX: number,
    endY: number,
  ): Array<{ x: number; y: number }> {
    if (!this.collisionLayer) {
      // No collision layer — direct walk
      return [{ x: endX, y: endY }];
    }

    const startTileX = Math.floor(startX / TILE_SIZE);
    const startTileY = Math.floor(startY / TILE_SIZE);
    const endTileX = Math.floor(endX / TILE_SIZE);
    const endTileY = Math.floor(endY / TILE_SIZE);

    // If destination is blocked, find nearest unblocked tile
    if (this.isBlocked(endTileX, endTileY)) {
      return [{ x: endX, y: endY }]; // Just walk toward it, collision will stop us
    }

    const path = this.astar(startTileX, startTileY, endTileX, endTileY);
    if (!path || path.length === 0) {
      return [{ x: endX, y: endY }];
    }

    // Convert tile coords to world coords (center of tile)
    return path.map(({ x, y }) => ({
      x: x * TILE_SIZE + TILE_SIZE / 2,
      y: y * TILE_SIZE + TILE_SIZE / 2,
    }));
  }

  private isBlocked(tileX: number, tileY: number): boolean {
    if (!this.collisionLayer) return false;
    const tile = this.collisionLayer.getTileAt(tileX, tileY);
    return tile !== null;
  }

  /**
   * Find a path from start to a walkable tile ADJACENT to (targetX, targetY)
   * in world coordinates — for "walk over and stand next to" interactions
   * (e.g. waving at another avatar) where the target's own tile is occupied.
   * Prefers the nearest-to-start walkable neighbour; falls back to a direct
   * path to the target itself if every neighbour is blocked.
   */
  findPathAdjacentTo(
    startX: number,
    startY: number,
    targetX: number,
    targetY: number,
  ): Array<{ x: number; y: number }> {
    if (!this.collisionLayer) {
      return [{ x: targetX, y: targetY }];
    }

    const targetTileX = Math.floor(targetX / TILE_SIZE);
    const targetTileY = Math.floor(targetY / TILE_SIZE);
    const startTileX = Math.floor(startX / TILE_SIZE);
    const startTileY = Math.floor(startY / TILE_SIZE);

    const NEIGHBOR_DIRS = [
      { dx: 0, dy: -1 },
      { dx: 0, dy: 1 },
      { dx: -1, dy: 0 },
      { dx: 1, dy: 0 },
      { dx: -1, dy: -1 },
      { dx: 1, dy: -1 },
      { dx: -1, dy: 1 },
      { dx: 1, dy: 1 },
    ];

    let bestTile: { x: number; y: number } | null = null;
    let bestDist = Infinity;
    for (const dir of NEIGHBOR_DIRS) {
      const nx = targetTileX + dir.dx;
      const ny = targetTileY + dir.dy;
      if (this.isBlocked(nx, ny)) continue;
      const dist = this.heuristic(startTileX, startTileY, nx, ny);
      if (dist < bestDist) {
        bestDist = dist;
        bestTile = { x: nx, y: ny };
      }
    }

    if (!bestTile) {
      // Every neighbour is blocked — fall back to walking toward the target
      // itself; collision will stop the avatar at the nearest reachable tile.
      return [{ x: targetX, y: targetY }];
    }

    const destX = bestTile.x * TILE_SIZE + TILE_SIZE / 2;
    const destY = bestTile.y * TILE_SIZE + TILE_SIZE / 2;
    return this.findPath(startX, startY, destX, destY);
  }

  private heuristic(ax: number, ay: number, bx: number, by: number): number {
    return Math.abs(ax - bx) + Math.abs(ay - by);
  }

  private astar(
    sx: number,
    sy: number,
    ex: number,
    ey: number,
  ): Array<{ x: number; y: number }> | null {
    const gridW = Math.ceil(this.worldWidth / TILE_SIZE);
    const gridH = Math.ceil(this.worldHeight / TILE_SIZE);

    const open: PathNode[] = [];
    const closed = new Set<string>();
    const key = (x: number, y: number) => `${x},${y}`;

    const start: PathNode = {
      x: sx,
      y: sy,
      g: 0,
      h: this.heuristic(sx, sy, ex, ey),
      f: 0,
      parent: null,
    };
    start.f = start.g + start.h;
    open.push(start);

    const DIRS = [
      { dx: 0, dy: -1 },
      { dx: 0, dy: 1 },
      { dx: -1, dy: 0 },
      { dx: 1, dy: 0 },
    ];

    let iterations = 0;
    const MAX_ITERATIONS = 2000;

    while (open.length > 0 && iterations < MAX_ITERATIONS) {
      iterations++;
      // Find node with lowest f
      let bestIdx = 0;
      for (let i = 1; i < open.length; i++) {
        if (open[i].f < open[bestIdx].f) bestIdx = i;
      }
      const current = open.splice(bestIdx, 1)[0];

      if (current.x === ex && current.y === ey) {
        // Reconstruct path
        const path: Array<{ x: number; y: number }> = [];
        let node: PathNode | null = current;
        while (node) {
          path.unshift({ x: node.x, y: node.y });
          node = node.parent;
        }
        // Skip the start node
        return path.slice(1);
      }

      closed.add(key(current.x, current.y));

      for (const dir of DIRS) {
        const nx = current.x + dir.dx;
        const ny = current.y + dir.dy;
        if (nx < 0 || ny < 0 || nx >= gridW || ny >= gridH) continue;
        if (closed.has(key(nx, ny))) continue;
        if (this.isBlocked(nx, ny)) continue;

        const g = current.g + 1;
        const h = this.heuristic(nx, ny, ex, ey);
        const f = g + h;

        const existing = open.find((n) => n.x === nx && n.y === ny);
        if (existing) {
          if (g < existing.g) {
            existing.g = g;
            existing.f = f;
            existing.parent = current;
          }
        } else {
          open.push({ x: nx, y: ny, g, h, f, parent: current });
        }
      }
    }

    return null; // No path found
  }
}
