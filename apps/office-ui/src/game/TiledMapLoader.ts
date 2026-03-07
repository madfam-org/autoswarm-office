import Phaser from 'phaser';

export interface DepartmentZone {
  slug: string;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  maxAgents: number;
  color: string;
}

export interface ReviewStationDef {
  departmentSlug: string;
  x: number;
  y: number;
}

export interface SpawnPoint {
  x: number;
  y: number;
  name: string;
}

export interface ParsedMap {
  tilemap: Phaser.Tilemaps.Tilemap;
  floorLayer: Phaser.Tilemaps.TilemapLayer | null;
  wallsLayer: Phaser.Tilemaps.TilemapLayer | null;
  furnitureLayer: Phaser.Tilemaps.TilemapLayer | null;
  decorationsLayer: Phaser.Tilemaps.TilemapLayer | null;
  collisionLayer: Phaser.Tilemaps.TilemapLayer | null;
  departments: DepartmentZone[];
  reviewStations: ReviewStationDef[];
  spawnPoints: SpawnPoint[];
  worldWidth: number;
  worldHeight: number;
}

function extractObjects<T>(
  objectLayer: Phaser.Tilemaps.ObjectLayer | null,
  mapper: (obj: Phaser.Types.Tilemaps.TiledObject) => T | null,
): T[] {
  if (!objectLayer) return [];
  const results: T[] = [];
  for (const obj of objectLayer.objects) {
    const mapped = mapper(obj);
    if (mapped) results.push(mapped);
  }
  return results;
}

function getProp(
  obj: Phaser.Types.Tilemaps.TiledObject,
  name: string,
): string | number | boolean | undefined {
  const props = obj.properties as
    | Array<{ name: string; value: string | number | boolean }>
    | undefined;
  if (!props) return undefined;
  const found = props.find((p) => p.name === name);
  return found?.value;
}

export function loadTiledMap(scene: Phaser.Scene): ParsedMap | null {
  try {
    if (!scene.cache.tilemap.has('office-map')) {
      return null;
    }

    const tilemap = scene.make.tilemap({ key: 'office-map' });
    const tileset = tilemap.addTilesetImage('office-tileset', 'office-tiles');
    if (!tileset) return null;

    const floorLayer = tilemap.createLayer('floor', tileset) ?? null;
    const wallsLayer = tilemap.createLayer('walls', tileset) ?? null;
    const furnitureLayer = tilemap.createLayer('furniture', tileset) ?? null;
    const decorationsLayer = tilemap.createLayer('decorations', tileset) ?? null;
    const collisionLayer = tilemap.createLayer('collision', tileset) ?? null;

    if (collisionLayer) {
      collisionLayer.setVisible(false);
      collisionLayer.setCollisionByExclusion([-1]);
    }

    const departments = extractObjects<DepartmentZone>(
      tilemap.getObjectLayer('departments'),
      (obj) => {
        const slug = getProp(obj, 'slug') as string | undefined;
        if (!slug) return null;
        return {
          slug,
          name: (getProp(obj, 'name') as string) ?? obj.name ?? slug,
          x: obj.x ?? 0,
          y: obj.y ?? 0,
          width: obj.width ?? 192,
          height: obj.height ?? 160,
          maxAgents: (getProp(obj, 'maxAgents') as number) ?? 4,
          color: (getProp(obj, 'color') as string) ?? '#1e3a5f',
        };
      },
    );

    const reviewStations = extractObjects<ReviewStationDef>(
      tilemap.getObjectLayer('review-stations'),
      (obj) => {
        const departmentSlug = getProp(obj, 'departmentSlug') as string | undefined;
        if (!departmentSlug) return null;
        return {
          departmentSlug,
          x: obj.x ?? 0,
          y: obj.y ?? 0,
        };
      },
    );

    const spawnPoints = extractObjects<SpawnPoint>(
      tilemap.getObjectLayer('spawn-points'),
      (obj) => ({
        x: obj.x ?? 400,
        y: obj.y ?? 300,
        name: obj.name ?? 'default',
      }),
    );

    return {
      tilemap,
      floorLayer,
      wallsLayer,
      furnitureLayer,
      decorationsLayer,
      collisionLayer,
      departments,
      reviewStations,
      spawnPoints,
      worldWidth: tilemap.widthInPixels,
      worldHeight: tilemap.heightInPixels,
    };
  } catch {
    return null;
  }
}
