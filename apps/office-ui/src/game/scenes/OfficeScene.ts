import Phaser from 'phaser';
import { GamepadManager } from '../GamepadManager';
import { gameEventBus } from '../PhaserGame';
import { loadTiledMap } from '../TiledMapLoader';
import type { DepartmentZone } from '../TiledMapLoader';
import { compositeAvatar, createAvatarAnimations } from '../AvatarCompositor';
import { VirtualJoystick } from '../VirtualJoystick';
import { TouchActionButtons } from '../TouchActionButtons';
import { InteractableManager } from '../InteractableManager';
import { ScriptBridge } from '../scripting/ScriptBridge';
import { AgentBehavior } from '../AgentBehavior';
import type { AnimationHint } from '../AgentBehavior';
import { CompanionBehavior } from '../CompanionBehavior';
import { Pathfinder } from '../Pathfinder';
import {
  TILE_SIZE,
  WORLD_COLS,
  WORLD_ROWS,
  TACTICIAN_SPEED,
  PROXIMITY_THRESHOLD,
  MOVE_THROTTLE_MS,
  EMOTE_DURATION_MS,
  ANIM_FADE_MS,
  DUST_MOTE_INTERVAL_MS,
  DUST_EMIT_INTERVAL_MS,
  STATUS_PARTICLE_INTERVAL_MS,
  SPAWN_OFFSET,
  SPAWN_GRID_SPACING,
  HALO_RADIUS,
  HALO_Y_OFFSET,
  EMOTE_Y_OFFSET,
  DEFAULT_SPAWN,
  LEGACY_FLOOR_EXTENT,
  SKYLIGHT_POSITIONS,
  ZONE_PARTICLE_REGIONS,
} from '../constants';
import {
  TILE_MONITOR_ON,
  TILE_PLANT_SMALL,
  TILE_PLANT_LARGE,
  TILE_COFFEE_MACHINE,
  TILE_SERVER_RACK,
  TILE_WATER_COOLER,
  TILE_CANDLE,
  TILE_GROW_LIGHT,
} from '../tile-ids';
import { EVENT_CHAT_FOCUS, EVENT_EMOTE_PICKER_FOCUS } from '../../lib/constants';
import type {
  OfficeState,
  Department,
  ReviewStation,
  Agent,
  Player,
  AvatarConfig,
} from '@selva/shared-types';

// === Feature Flags ===
const ENABLE_POST_FX = process.env.NEXT_PUBLIC_ENABLE_POST_FX !== 'false';
const ENABLE_PARTICLES = process.env.NEXT_PUBLIC_ENABLE_PARTICLES !== 'false';

/** Scale font size based on viewport width for readability */
function responsiveFontSize(base: number): string {
  const scale = Math.max(1, Math.min(window.innerWidth / 1280, 1.5));
  return `${Math.round(base * scale)}px`;
}

/** Maps emote type to spritesheet frame index */
const EMOTE_FRAME_MAP: Record<string, number> = {
  wave: 0,
  thumbsup: 1,
  heart: 2,
  laugh: 3,
  think: 4,
  clap: 5,
  fire: 6,
  sparkle: 7,
  coffee: 8,
};

/** Color mapping for companion types (used for simple rectangle sprites) */
const COMPANION_COLORS: Record<string, number> = {
  cat: 0xf59e0b,    // amber
  dog: 0x92400e,    // brown
  robot: 0x94a3b8,  // slate
  dragon: 0x22c55e, // green
  parrot: 0xef4444, // red
};

interface AgentSprite {
  sprite: Phaser.GameObjects.Sprite;
  alertIcon: Phaser.GameObjects.Image;
  statusHalo: Phaser.GameObjects.Arc;
  nameLabel: Phaser.GameObjects.Text;
  nameBackground: Phaser.GameObjects.Rectangle;
  nodeLabel: Phaser.GameObjects.Text | null;
  nodeLabelBackground: Phaser.GameObjects.Rectangle | null;
  agentId: string;
  agentStatus: string;
  hasPendingApproval: boolean;
  breathingTween: Phaser.Tweens.Tween | null;
  haloTween: Phaser.Tweens.Tween | null;
  lastParticleTime: number;
}

interface RemotePlayerSprite {
  sprite: Phaser.GameObjects.Sprite;
  label: Phaser.GameObjects.Text;
  statusDot: Phaser.GameObjects.Arc;
  musicLabel: Phaser.GameObjects.Text | null;
  targetX: number;
  targetY: number;
  direction: string;
  /** Texture key used as animation prefix (e.g. 'tactician' or 'avatar-...') */
  textureKey: string;
}

/** Department zone layout positions on the office grid (procedural fallback, 50x28 map) */
const DEPARTMENT_LAYOUT: Record<string, { x: number; y: number; w: number; h: number; label: string }> = {
  engineering: { x: 32, y: 32, w: 640, h: 320, label: 'ENGINEERING' },
  crm: { x: 928, y: 32, w: 640, h: 320, label: 'CRM' },
  support: { x: 32, y: 544, w: 640, h: 320, label: 'SUPPORT' },
  research: { x: 928, y: 544, w: 640, h: 320, label: 'RESEARCH' },
  blueprint: { x: 1248, y: 384, w: 320, h: 128, label: 'BLUEPRINT LAB' },
};

const AGENT_ROLES = ['planner', 'coder', 'reviewer', 'researcher', 'crm', 'support'] as const;

export class OfficeScene extends Phaser.Scene {
  private gamepadManager!: GamepadManager;
  private tactician: Phaser.GameObjects.Sprite | undefined;
  private tacticianLabel!: Phaser.GameObjects.Text;
  private agentSprites: Map<string, AgentSprite> = new Map();
  private remotePlayers: Map<string, RemotePlayerSprite> = new Map();
  private departmentZones: Phaser.GameObjects.Image[] = [];
  private departmentLayouts: Map<string, { x: number; y: number; w?: number; h?: number; label: string }> = new Map();
  private reviewStations: Map<string, Phaser.GameObjects.Image> = new Map();
  private officeState: OfficeState | null = null;
  private localSessionId: string = '';
  private stateCleanup: (() => void) | null = null;
  private sessionIdCleanup: (() => void) | null = null;
  private emoteCleanup: (() => void) | null = null;
  private emotePickerCleanup: (() => void) | null = null;
  private avatarConfigCleanup: (() => void) | null = null;
  private zoneEnterCleanup: (() => void) | null = null;
  private zoneLeaveCleanup: (() => void) | null = null;
  private walkToEntityCleanup: (() => void) | null = null;
  /** Sequence id of the last handled 'walk-to-entity' command — guards
   * against the event bus replaying a stale cached command to a scene that
   * remounts (e.g. a map/room transition) after the walk was issued. */
  private lastWalkToSeq: number = 0;
  /** Set while following a click/walk-to path; fired once on arrival. */
  private pendingArrivalAction: (() => void) | null = null;
  private localAvatarConfig: AvatarConfig | null = null;
  private virtualJoystick: VirtualJoystick | null = null;
  private touchButtons: TouchActionButtons | null = null;
  private interactableManager: InteractableManager | null = null;
  private scriptBridge: ScriptBridge | null = null;
  private isTouchDevice: boolean = false;
  private helpOverlay!: Phaser.GameObjects.Container;
  private lastDirection: string = 'down';
  /** Current texture key used for the local tactician animation prefix */
  private localTextureKey: string = 'tactician';
  private lastMoveTime: number = 0;
  private lastSentX: number = 0;
  private lastSentY: number = 0;
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;
  private spawnPoints: Array<{ x: number; y: number; name: string }> = [];
  private worldWidth: number = 1600;
  private worldHeight: number = 896;
  private dustEmitter: Phaser.GameObjects.Particles.ParticleEmitter | null = null;
  private lastDustEmitTime: number = 0;
  private ambientEmitter: Phaser.GameObjects.Particles.ParticleEmitter | null = null;
  private agentBehavior: AgentBehavior = new AgentBehavior();
  private clickPath: Array<{ x: number; y: number }> = [];
  private clickPathIndex: number = 0;
  private pathfinder: Pathfinder | null = null;
  private clickMarker: Phaser.GameObjects.Arc | null = null;
  private followTarget: string | null = null;
  private followLabel: Phaser.GameObjects.Text | null = null;
  private explorerMode: boolean = false;
  private explorerPrevZoom: number = 1;
  private companionBehavior: CompanionBehavior = new CompanionBehavior();
  private companionSprites: Map<string, Phaser.GameObjects.Rectangle> = new Map();

  // === Animated Tile System ===
  private animatedTileOverlays: Array<{
    graphics: Phaser.GameObjects.Rectangle[];
    frames: Array<{ color: number; alpha: number }[]>;
    frameDuration: number;
    currentFrame: number;
    elapsed: number;
  }> = [];
  private tileAnimTimer: Phaser.Time.TimerEvent | null = null;

  constructor() {
    super({ key: 'OfficeScene' });
  }

  create(): void {
    this.createAnimations();

    this.gamepadManager = new GamepadManager();

    // Try Tiled map first, fall back to procedural
    const mapData = loadTiledMap(this);
    if (mapData) {
      this.initFromTiledMap(mapData);
    } else {
      this.initProceduralMap();
    }

    this.createTactician();

    // Listen for state updates from React
    this.stateCleanup = gameEventBus.on('state-update', (detail) => {
      this.onStateUpdate(detail as OfficeState);
    });

    // Listen for session ID from React
    this.sessionIdCleanup = gameEventBus.on('session-id', (detail) => {
      this.localSessionId = detail as string;
    });

    // Listen for chat focus to suppress game input while typing
    gameEventBus.on(EVENT_CHAT_FOCUS, (detail) => {
      this.gamepadManager.setChatFocused(detail as boolean);
    });

    // Listen for emote picker focus
    this.emotePickerCleanup = gameEventBus.on(EVENT_EMOTE_PICKER_FOCUS, (detail) => {
      this.gamepadManager.setEmotePickerFocused(detail as boolean);
    });

    // Listen for emote broadcasts from server (via PhaserGame bridge)
    this.emoteCleanup = gameEventBus.on('player-emote', (detail) => {
      const { sessionId, emoteType } = detail as { sessionId: string; emoteType: string };
      this.showEmoteBubble(sessionId, emoteType);
    });

    // Listen for avatar config updates from React
    this.avatarConfigCleanup = gameEventBus.on('avatar-config', (detail) => {
      this.localAvatarConfig = detail as AvatarConfig;
      this.updateLocalAvatarTexture();
    });

    // Set up interactable manager after tactician is created
    this.interactableManager = new InteractableManager(this, this.tactician!);
    if (this._pendingTilemap) {
      this.interactableManager.loadFromTilemap(this._pendingTilemap);
      this.loadMapScripts(this._pendingTilemap);
      this._pendingTilemap = null;
    }

    // Forward zone enter/leave events to script bridge
    this.zoneEnterCleanup = gameEventBus.on('zone_enter', (detail) => {
      const { areaName } = detail as { areaName: string };
      this.scriptBridge?.notifyAreaEvent(areaName, 'enter');
    });
    this.zoneLeaveCleanup = gameEventBus.on('zone_leave', (detail) => {
      const { areaName } = detail as { areaName: string };
      this.scriptBridge?.notifyAreaEvent(areaName, 'leave');
    });

    // Wave -> walk-over: roster/person-card sends {kind, id, seq}; walk the
    // local avatar to stand next to the target, then wave on arrival.
    this.walkToEntityCleanup = gameEventBus.on('walk-to-entity', (detail) => {
      this.handleWalkToEntity(detail as { kind: 'player' | 'agent'; id: string; seq: number });
    });

    // Add keyboard instructions text
    this.add
      .text(this.worldWidth / 2, this.worldHeight - 8, 'WASD: Move | ENTER: Approve | ESC: Deny | E: Interact | T: Chat | R: Emote | [?] Help', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: responsiveFontSize(8),
        color: '#94a3b8',
      })
      .setOrigin(0.5)
      .setScrollFactor(0);

    this.createHelpOverlay();

    // Mobile touch controls
    this.isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    if (this.isTouchDevice) {
      this.virtualJoystick = new VirtualJoystick(this);
      this.touchButtons = new TouchActionButtons(this, {
        onApprove: () => this.handleProximityInteraction('approve'),
        onDeny: () => gameEventBus.emit('approval-deny', null),
        onInspect: () => this.handleProximityInteraction('inspect'),
        onEmote: () => gameEventBus.emit('emote-picker-toggle', null),
      });
      // Zoom in a bit more on mobile for better visibility
      this.cameras.main.setZoom(window.innerHeight > window.innerWidth ? 1.5 : 1.2);
      this.scale.on('resize', () => {
        this.cameras.main.setZoom(window.innerHeight > window.innerWidth ? 1.5 : 1.2);
      });
    }

    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      if (this.gamepadManager.isFocused()) return;
      if (event.key === '?') {
        this.helpOverlay.setVisible(!this.helpOverlay.visible);
      }
      // F = follow nearest player
      if (event.code === 'KeyF') {
        this.toggleFollowNearestPlayer();
      }
      // Tab = toggle explorer mode
      if (event.code === 'Tab') {
        event.preventDefault();
        this.toggleExplorerMode();
      }
      // Escape cancels follow and explorer
      if (event.code === 'Escape') {
        if (this.followTarget) this.cancelFollow();
        if (this.explorerMode) this.toggleExplorerMode();
      }
    });

    // === Post-FX: CRT vignette (lighter) ===
    if (ENABLE_POST_FX && this.cameras.main.postFX) {
      this.cameras.main.postFX.addVignette(0.5, 0.5, 0.9, 0.15);
    }

    // === Floating leaves (solarpunk ambient) ===
    if (ENABLE_PARTICLES && this.textures.exists('particle-leaf')) {
      this.ambientEmitter = this.add.particles(0, 0, 'particle-leaf', {
        x: { min: 0, max: this.worldWidth },
        y: -10,
        lifespan: 8000,
        speedX: { min: -15, max: 15 },
        speedY: { min: 8, max: 20 },
        alpha: { start: 0, end: 0, ease: 'Sine.easeInOut',
          interpolation: [0, 0.5, 0.4, 0] as unknown as string },
        rotate: { min: 0, max: 360 },
        frequency: 2000,
        blendMode: 'NORMAL',
      });
      this.ambientEmitter.setDepth(1);
    }

    // === Fireflies (solarpunk ambient, wandering) ===
    if (ENABLE_PARTICLES && this.textures.exists('particle-firefly')) {
      const fireflyEmitter = this.add.particles(0, 0, 'particle-firefly', {
        x: { min: 100, max: this.worldWidth - 100 },
        y: { min: 100, max: this.worldHeight - 100 },
        lifespan: 4000,
        speed: { min: 5, max: 15 },
        alpha: { start: 0, end: 0, ease: 'Sine.easeInOut',
          interpolation: [0, 0.8, 0.3, 0.9, 0] as unknown as string },
        frequency: 3000,
        blendMode: 'ADD',
      });
      fireflyEmitter.setDepth(1);
    }

    // === Skylight light pools (warm golden pools on the floor) ===
    if (ENABLE_PARTICLES) {
      for (const sky of SKYLIGHT_POSITIONS) {
        // Light pool circle
        const pool = this.add.circle(
          sky.x * TILE_SIZE + TILE_SIZE / 2,
          sky.y * TILE_SIZE + TILE_SIZE / 2,
          TILE_SIZE * 3,  // 3-tile radius
          0xf6d55c,       // Solar gold
          0.06,
        );
        pool.setBlendMode(Phaser.BlendModes.ADD);
        pool.setDepth(1);

        // Gentle pulsing animation
        this.tweens.add({
          targets: pool,
          alpha: { from: 0.04, to: 0.08 },
          duration: 4000,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });

        // Solar sparkle particles in light pools
        if (this.textures.exists('particle-glint')) {
          this.add.particles(
            sky.x * TILE_SIZE + TILE_SIZE / 2,
            sky.y * TILE_SIZE + TILE_SIZE / 2,
            'particle-glint',
            {
              speed: { min: 2, max: 8 },
              alpha: { start: 0, end: 0, ease: 'Sine.easeInOut',
                interpolation: [0, 0.6, 0] as unknown as string },
              lifespan: 3000,
              frequency: 4000,
              emitZone: {
                type: 'random',
                source: new Phaser.Geom.Circle(0, 0, TILE_SIZE * 2),
              } as Phaser.Types.GameObjects.Particles.ParticleEmitterRandomZoneConfig,
              blendMode: 'ADD',
            },
          );
        }
      }
    }

    // === Zone-specific solarpunk particle effects ===
    if (ENABLE_PARTICLES) {
      // Engineering: subtle purple grow-light sparkles (emit from top of zone)
      if (this.textures.exists('particle-spore')) {
        const eng = ZONE_PARTICLE_REGIONS.engineering;
        this.add.particles(0, 0, 'particle-spore', {
          emitZone: {
            type: 'random',
            source: new Phaser.Geom.Rectangle(
              eng.x * TILE_SIZE, eng.y * TILE_SIZE,
              eng.w * TILE_SIZE, eng.h * TILE_SIZE,
            ),
          } as Phaser.Types.GameObjects.Particles.ParticleEmitterRandomZoneConfig,
          speedY: { min: 3, max: 10 },
          alpha: { start: 0, end: 0,
            interpolation: [0, 0.4, 0] as unknown as string },
          lifespan: 5000,
          frequency: 3000,
          tint: 0xbb88ff,  // Purple tint for grow lights
          blendMode: 'ADD',
        });
      }

      // Support: zen water ripple sparkles
      if (this.textures.exists('particle-sparkle')) {
        const sup = ZONE_PARTICLE_REGIONS.support;
        this.add.particles(0, 0, 'particle-sparkle', {
          emitZone: {
            type: 'random',
            source: new Phaser.Geom.Rectangle(
              sup.x * TILE_SIZE, sup.y * TILE_SIZE,
              sup.w * TILE_SIZE, sup.h * TILE_SIZE,
            ),
          } as Phaser.Types.GameObjects.Particles.ParticleEmitterRandomZoneConfig,
          speed: { min: 1, max: 5 },
          alpha: { start: 0, end: 0,
            interpolation: [0, 0.3, 0] as unknown as string },
          lifespan: 4000,
          frequency: 5000,
          tint: 0x87ceeb,  // Cool water blue
          blendMode: 'ADD',
        });
      }

      // Atrium: bioluminescent spores rising
      if (this.textures.exists('particle-spore')) {
        const atr = ZONE_PARTICLE_REGIONS.atrium;
        this.add.particles(0, 0, 'particle-spore', {
          x: { min: atr.xMin * TILE_SIZE, max: atr.xMax * TILE_SIZE },
          y: atr.y * TILE_SIZE,
          speedY: { min: -5, max: -15 },
          speedX: { min: -3, max: 3 },
          alpha: { start: 0, end: 0,
            interpolation: [0, 0.5, 0.3, 0] as unknown as string },
          lifespan: 6000,
          frequency: 2000,
          blendMode: 'ADD',
        });
      }
    }

    // === Dust trail emitter (inactive, emitted on movement) ===
    if (ENABLE_PARTICLES && this.textures.exists('particle-dust')) {
      this.dustEmitter = this.add.particles(0, 0, 'particle-dust', {
        lifespan: 400,
        alpha: { start: 0.4, end: 0 },
        scale: { start: 0.8, end: 0.3 },
        speedY: { min: -10, max: -5 },
        speedX: { min: -8, max: 8 },
        emitting: false,
      });
      this.dustEmitter.setDepth(2);
    }
  }

  private initFromTiledMap(mapData: ReturnType<typeof loadTiledMap> & object): void {
    const data = mapData as NonNullable<ReturnType<typeof loadTiledMap>>;
    this.worldWidth = data.worldWidth;
    this.worldHeight = data.worldHeight;
    this.collisionLayer = data.collisionLayer;
    if (data.spawnPoints?.length) {
      this.spawnPoints = data.spawnPoints.map((sp) => ({ x: sp.x, y: sp.y, name: sp.name }));
    }

    // Populate department layouts from Tiled data, falling back to hardcoded
    if (data.departments.length > 0) {
      for (const dept of data.departments) {
        this.departmentLayouts.set(dept.slug, {
          x: dept.x,
          y: dept.y,
          w: dept.width,
          h: dept.height,
          label: dept.name.toUpperCase(),
        });
      }
    } else {
      for (const [slug, layout] of Object.entries(DEPARTMENT_LAYOUT)) {
        this.departmentLayouts.set(slug, layout);
      }
    }

    // If no floor layer, render procedural floor
    if (!data.floorLayer) {
      this.createFloor();
    }

    // Always render department zone overlays (Tiled object layer doesn't create visuals)
    this.createDepartmentZones();

    // Create animated furniture overlays (monitor flicker, plant sway)
    if (data.furnitureLayer) {
      this.createAnimatedProps(data.furnitureLayer);
      this.setupTileAnimations(data.furnitureLayer);
    }

    // Load interactables from Tiled object layer (manager created after tactician)
    // Deferred to after createTactician, but we store the tilemap reference
    this._pendingTilemap = data.tilemap;
  }

  /**
   * Scan the furniture tilemap layer and add animated overlays at specific
   * tile positions (monitor flicker, plant sway, server LED blinks).
   */
  private createAnimatedProps(furnitureLayer: Phaser.Tilemaps.TilemapLayer): void {
    if (!ENABLE_PARTICLES) return;

    // Tile IDs imported from `../tile-ids` (canonical names: monitor_on=33,
    // plant_small=35, plant_large=36, coffee_machine=39, server_rack=41).
    furnitureLayer.forEachTile((tile) => {
      if (!tile || tile.index <= 0) return;
      const worldX = tile.pixelX + 16;
      const worldY = tile.pixelY + 16;

      if (tile.index === TILE_MONITOR_ON) {
        // Monitor screen flicker: subtle alpha glow rectangle
        const glow = this.add.rectangle(worldX, worldY - 4, 12, 8, 0x67e8f9, 0.15);
        glow.setDepth(3);
        this.tweens.add({
          targets: glow,
          alpha: { from: 0.05, to: 0.2 },
          duration: 2000,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });
      }

      if (tile.index === TILE_PLANT_SMALL || tile.index === TILE_PLANT_LARGE) {
        // Plant sway: gentle oscillation overlay
        const leaf = this.add.rectangle(worldX, worldY - 6, 6, 4, 0x2d8a4e, 0.2);
        leaf.setDepth(3);
        this.tweens.add({
          targets: leaf,
          x: worldX + 1.5,
          duration: 3000 + Math.random() * 1000,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });
      }

      if (tile.index === TILE_SERVER_RACK && this.textures.exists('particle-dot')) {
        // Server LED blinks
        this.add.particles(worldX + 6, worldY - 8, 'particle-dot', {
          lifespan: 600,
          frequency: 500,
          alpha: { start: 0.8, end: 0 },
          scale: 0.5,
          tint: [0x22c55e, 0xf59e0b],
          speedY: 0,
          speedX: 0,
          blendMode: 'ADD',
        }).setDepth(3);
      }

      if (tile.index === TILE_COFFEE_MACHINE && this.textures.exists('particle-dot')) {
        // Coffee steam
        this.add.particles(worldX, worldY - 10, 'particle-dot', {
          lifespan: 1500,
          frequency: 400,
          alpha: { start: 0.3, end: 0 },
          scale: { start: 0.3, end: 0.8 },
          speedY: { min: -15, max: -8 },
          speedX: { min: -3, max: 3 },
          tint: 0x94a3b8,
        }).setDepth(3);
      }
    });
  }

  /**
   * Set up animated tile overlays on the decoration/furniture layer.
   * Scans for specific tile IDs and creates cycling color overlays
   * that simulate water shimmer, candle flicker, and grow-light pulses.
   */
  private setupTileAnimations(furnitureLayer: Phaser.Tilemaps.TilemapLayer): void {
    // Animated tile definitions: map furniture tile IDs to overlay behavior.
    // Each entry creates a small colored rectangle overlay that cycles alpha/color.
    // The aliases (WATER_COOLER, CANDLE, GROW_LIGHT) intentionally map to the
    // same physical tile sprites as the canonical names — see ../tile-ids.ts
    // for the rationale (theme-dependent semantic re-use).
    const animDefs: Array<{
      tileId: number;
      colors: number[];
      alphas: number[];
      duration: number;
      offsetY: number;
      width: number;
      height: number;
    }> = [
      {
        tileId: TILE_WATER_COOLER,
        colors: [0x67e8f9, 0xa8dadc, 0x67e8f9, 0xa8dadc],
        alphas: [0.1, 0.18, 0.14, 0.08],
        duration: 250,
        offsetY: 2,
        width: 10,
        height: 6,
      },
      {
        tileId: TILE_CANDLE,
        colors: [0xf6d55c, 0xf59e0b, 0xf6d55c, 0xd4a43a],
        alphas: [0.2, 0.3, 0.25, 0.15],
        duration: 200,
        offsetY: -8,
        width: 6,
        height: 6,
      },
      {
        tileId: TILE_GROW_LIGHT,
        colors: [0x9b59b6, 0xbb88ff, 0xd4b0ff, 0xbb88ff],
        alphas: [0.1, 0.2, 0.3, 0.2],
        duration: 400,
        offsetY: -6,
        width: 10,
        height: 4,
      },
    ];

    furnitureLayer.forEachTile((tile) => {
      if (!tile || tile.index <= 0) return;

      for (const def of animDefs) {
        if (tile.index !== def.tileId) continue;

        const worldX = tile.pixelX + 16;
        const worldY = tile.pixelY + 16 + def.offsetY;

        // Create a single rectangle overlay that we'll tween through color/alpha
        const overlay = this.add.rectangle(
          worldX, worldY, def.width, def.height,
          def.colors[0], def.alphas[0],
        ).setDepth(3);

        // Store frames as color+alpha pairs for cycling
        const frames = def.colors.map((color, i) => ({
          color,
          alpha: def.alphas[i],
        }));

        this.animatedTileOverlays.push({
          graphics: [overlay],
          frames: [frames],
          frameDuration: def.duration,
          currentFrame: 0,
          elapsed: 0,
        });
      }
    });

    // Single timer drives all animated tile overlays
    if (this.animatedTileOverlays.length > 0) {
      this.tileAnimTimer = this.time.addEvent({
        delay: 50, // tick at 20Hz, frame switching handled by elapsed time
        callback: () => {
          for (const anim of this.animatedTileOverlays) {
            anim.elapsed += 50;
            if (anim.elapsed >= anim.frameDuration) {
              anim.elapsed = 0;
              anim.currentFrame = (anim.currentFrame + 1) % anim.frames[0].length;
              for (let i = 0; i < anim.graphics.length; i++) {
                const frame = anim.frames[i][anim.currentFrame];
                anim.graphics[i].setFillStyle(frame.color, frame.alpha);
              }
            }
          }
        },
        loop: true,
      });
    }
  }

  /** Tilemap reference for deferred interactable loading */
  private _pendingTilemap: Phaser.Tilemaps.Tilemap | null = null;

  /**
   * Check for scriptUrl properties on the tilemap and load them via ScriptBridge.
   */
  private loadMapScripts(tilemap: Phaser.Tilemaps.Tilemap): void {
    const rawProps = tilemap.properties;
    if (!rawProps || !Array.isArray(rawProps)) return;

    const mapProps = rawProps as Array<{ name: string; value: string | number | boolean }>;
    const scriptProp = mapProps.find((p) => p.name === 'scriptUrl');
    if (!scriptProp || typeof scriptProp.value !== 'string') return;

    this.scriptBridge = new ScriptBridge(this);
    this.scriptBridge.loadScript(scriptProp.value);
  }

  private initProceduralMap(): void {
    // Populate layouts from hardcoded defaults
    for (const [slug, layout] of Object.entries(DEPARTMENT_LAYOUT)) {
      this.departmentLayouts.set(slug, layout);
    }
    this.createFloor();
    this.createDepartmentZones();
  }

  update(): void {
    // Hot-path null safety: tactician may be undefined if loadTiledMap()
    // failed before createTactician() ran, or after shutdown() cleared it.
    if (!this.tactician) return;
    this.gamepadManager.poll();
    const input = this.gamepadManager.getInput();

    // Merge virtual joystick input with gamepad/keyboard
    let stickX = input.leftStickX;
    let stickY = input.leftStickY;
    if (this.virtualJoystick && (this.virtualJoystick.axisX !== 0 || this.virtualJoystick.axisY !== 0)) {
      stickX = this.virtualJoystick.axisX;
      stickY = this.virtualJoystick.axisY;
    }

    // Explorer mode: scroll-to-pan with sticks, skip player movement
    if (this.explorerMode) {
      if (stickX !== 0 || stickY !== 0) {
        const panSpeed = 400 * (this.game.loop.delta / 1000);
        this.cameras.main.scrollX += stickX * panSpeed;
        this.cameras.main.scrollY += stickY * panSpeed;
      }
      // Still update interactables and agents in explorer mode
      if (this.interactableManager) this.interactableManager.update();
      const explorerDelta = this.game.loop.delta;
      this.agentSprites.forEach((agentSprite) => {
        const deptSlug = this.findAgentDepartmentSlug(agentSprite.agentId);
        const layout = deptSlug ? this.departmentLayouts.get(deptSlug) : null;
        const fallback = DEPARTMENT_LAYOUT[deptSlug?.replace('dept-', '') ?? ''];
        const zoneW = layout?.w ?? fallback?.w ?? 640;
        const zoneH = layout?.h ?? fallback?.h ?? 320;
        const zoneBounds = layout ? { x: layout.x, y: layout.y, width: zoneW, height: zoneH } : null;
        const stationSprite = deptSlug ? this.reviewStations.get(deptSlug) : null;
        const reviewStation = stationSprite ? { x: stationSprite.x, y: stationSprite.y } : null;
        const result = this.agentBehavior.update(agentSprite.agentId, agentSprite.sprite.x, agentSprite.sprite.y, explorerDelta, zoneBounds, reviewStation);
        if (result) {
          agentSprite.sprite.setPosition(result.x, result.y);
          agentSprite.statusHalo.setPosition(result.x, result.y + 4);
          agentSprite.nameLabel.setPosition(result.x, result.y + 20);
          agentSprite.nameBackground.setPosition(result.x, result.y + 23);
          agentSprite.alertIcon.setPosition(result.x + 12, result.y - 20);
          if (result.animHint) {
            this.applyAnimationHint(agentSprite, result.animHint);
          }
        }
      });
      return;
    }

    // Cancel follow on manual movement input
    if (this.followTarget && (stickX !== 0 || stickY !== 0)) {
      this.cancelFollow();
    }

    // Click-to-move: follow path (cancelled by keyboard/gamepad input)
    if (this.clickPath.length > 0 && this.clickPathIndex < this.clickPath.length) {
      if (stickX !== 0 || stickY !== 0) {
        // Manual input cancels click path (and any pending arrival action —
        // the player steered away, so don't wave at a target they didn't reach)
        this.clickPath = [];
        this.clickPathIndex = 0;
        this.pendingArrivalAction = null;
      } else {
        const wp = this.clickPath[this.clickPathIndex];
        const cdx = wp.x - this.tactician.x;
        const cdy = wp.y - this.tactician.y;
        const cdist = Math.sqrt(cdx * cdx + cdy * cdy);
        if (cdist < 4) {
          this.clickPathIndex++;
          if (this.clickPathIndex >= this.clickPath.length) {
            this.clickPath = [];
            this.clickPathIndex = 0;
            if (this.pendingArrivalAction) {
              const action = this.pendingArrivalAction;
              this.pendingArrivalAction = null;
              action();
            }
          }
        } else {
          stickX = cdx / cdist;
          stickY = cdy / cdist;
        }
      }
    }

    // Move tactician based on input
    const dx = stickX * TACTICIAN_SPEED * (this.game.loop.delta / 1000);
    const dy = stickY * TACTICIAN_SPEED * (this.game.loop.delta / 1000);

    if (dx !== 0 || dy !== 0) {
      const newX = Phaser.Math.Clamp(this.tactician.x + dx, 16, this.worldWidth - 16);
      const newY = Phaser.Math.Clamp(this.tactician.y + dy, 16, this.worldHeight - 16);

      // Tile-based collision: check if destination is blocked
      if (this.collisionLayer) {
        const tileX = this.collisionLayer.getTileAtWorldXY(newX, this.tactician.y);
        const tileY = this.collisionLayer.getTileAtWorldXY(this.tactician.x, newY);
        if (!tileX) this.tactician.x = newX;
        if (!tileY) this.tactician.y = newY;
      } else {
        this.tactician.x = newX;
        this.tactician.y = newY;
      }

      // Determine direction for walk animation
      if (Math.abs(dx) > Math.abs(dy)) {
        this.lastDirection = dx > 0 ? 'right' : 'left';
      } else {
        this.lastDirection = dy > 0 ? 'down' : 'up';
      }

      const walkKey = `${this.localTextureKey}-walk-${this.lastDirection}`;
      if (this.anims.exists(walkKey) && this.tactician.anims.currentAnim?.key !== walkKey) {
        this.tactician.play(walkKey);
      }

      // Dust trail when walking — throttled to ~12fps (DUST_EMIT_INTERVAL_MS)
      // to avoid emitting on every frame (~60Hz). At 80ms intervals the
      // visible density is unchanged but particle pressure drops ~80%.
      const now = this.time.now;
      const positionDelta = Math.abs(this.tactician.x - this.lastSentX) + Math.abs(this.tactician.y - this.lastSentY);
      if (
        this.dustEmitter &&
        positionDelta > 1 &&
        now - this.lastDustEmitTime > DUST_EMIT_INTERVAL_MS
      ) {
        this.dustEmitter.emitParticleAt(this.tactician.x, this.tactician.y + 12, 1);
        this.lastDustEmitTime = now;
      }

      // Broadcast movement throttled to ~15fps
      if (now - this.lastMoveTime > MOVE_THROTTLE_MS && positionDelta > 1) {
        this.lastMoveTime = now;
        this.lastSentX = this.tactician.x;
        this.lastSentY = this.tactician.y;
        gameEventBus.emit('player-move', { x: this.tactician.x, y: this.tactician.y });
      }
    } else {
      // Idle: show single frame for current direction
      const idleKey = `${this.localTextureKey}-idle-${this.lastDirection}`;
      if (this.anims.exists(idleKey) && this.tactician.anims.currentAnim?.key !== idleKey) {
        this.tactician.play(idleKey);
      }
    }

    // Update label position
    if (this.tacticianLabel) {
      this.tacticianLabel.setPosition(this.tactician.x, this.tactician.y - 24);
    }

    // Update local player companion position
    const localCompanionRect = this.companionSprites.get(this.localSessionId);
    if (localCompanionRect) {
      const localCompResult = this.companionBehavior.update(
        this.localSessionId,
        this.tactician.x,
        this.tactician.y,
        this.game.loop.delta,
      );
      if (localCompResult) {
        localCompanionRect.setPosition(localCompResult.x, localCompResult.y);
      }
    }

    // Interpolate remote players toward their target positions
    const companionDelta = this.game.loop.delta;
    this.remotePlayers.forEach((remote, sessionId) => {
      const lerpFactor = 0.15;
      remote.sprite.x += (remote.targetX - remote.sprite.x) * lerpFactor;
      remote.sprite.y += (remote.targetY - remote.sprite.y) * lerpFactor;
      remote.label.setPosition(remote.sprite.x, remote.sprite.y - 24);
      remote.statusDot.setPosition(remote.sprite.x - 20, remote.sprite.y - 24);
      if (remote.musicLabel) {
        remote.musicLabel.setPosition(remote.sprite.x, remote.sprite.y - 16);
      }

      // Play walk/idle animation based on movement (per-texture animation keys)
      const animPrefix = remote.textureKey;
      const moving = Math.abs(remote.targetX - remote.sprite.x) > 0.5 ||
        Math.abs(remote.targetY - remote.sprite.y) > 0.5;
      if (moving) {
        const walkKey = `${animPrefix}-walk-${remote.direction}`;
        if (this.anims.exists(walkKey) && remote.sprite.anims.currentAnim?.key !== walkKey) {
          remote.sprite.play(walkKey);
        }
      } else {
        const idleKey = `${animPrefix}-idle-${remote.direction}`;
        if (this.anims.exists(idleKey) && remote.sprite.anims.currentAnim?.key !== idleKey) {
          remote.sprite.play(idleKey);
        }
      }

      // Update companion position (trail behind owner)
      const companionRect = this.companionSprites.get(sessionId);
      if (companionRect) {
        const result = this.companionBehavior.update(
          sessionId,
          remote.sprite.x,
          remote.sprite.y,
          companionDelta,
        );
        if (result) {
          companionRect.setPosition(result.x, result.y);
        }
      }
    });

    // Update interactable zones
    if (this.interactableManager) {
      this.interactableManager.update();
    }

    // Check button presses for proximity interactions
    if (input.buttonA) {
      this.handleProximityInteraction('approve');
    }
    if (input.buttonX) {
      // If overlapping an interactable, interact with it; otherwise inspect agent
      if (this.interactableManager?.hasActiveOverlap()) {
        this.interactableManager.interact();
      } else {
        this.handleProximityInteraction('inspect');
      }
    }

    // Update agent movement behavior
    const delta = this.game.loop.delta;
    this.agentSprites.forEach((agentSprite) => {
      const deptSlug = this.findAgentDepartmentSlug(agentSprite.agentId);
      const layout = deptSlug ? this.departmentLayouts.get(deptSlug) : null;
      const fallback = DEPARTMENT_LAYOUT[deptSlug?.replace('dept-', '') ?? ''];
      const zoneW = layout?.w ?? fallback?.w ?? 640;
      const zoneH = layout?.h ?? fallback?.h ?? 320;
      const zoneBounds = layout ? { x: layout.x, y: layout.y, width: zoneW, height: zoneH } : null;

      const stationSprite = deptSlug ? this.reviewStations.get(deptSlug) : null;
      const reviewStation = stationSprite ? { x: stationSprite.x, y: stationSprite.y } : null;

      const result = this.agentBehavior.update(
        agentSprite.agentId,
        agentSprite.sprite.x,
        agentSprite.sprite.y,
        delta,
        zoneBounds,
        reviewStation,
      );

      if (result) {
        agentSprite.sprite.setPosition(result.x, result.y);
        agentSprite.statusHalo.setPosition(result.x, result.y + 4);
        agentSprite.nameLabel.setPosition(result.x, result.y + 20);
        agentSprite.nameBackground.setPosition(result.x, result.y + 23);
        agentSprite.alertIcon.setPosition(result.x + 12, result.y - 20);

        // Apply enhanced animation hints from behavior system
        if (result.animHint) {
          this.applyAnimationHint(agentSprite, result.animHint);
        }
      }
    });

    // Animate alert icons + agent status particles
    const updateTime = this.time.now;
    this.agentSprites.forEach((agentSprite) => {
      if (agentSprite.hasPendingApproval) {
        agentSprite.alertIcon.setVisible(true);
        agentSprite.alertIcon.setPosition(
          agentSprite.sprite.x + 12,
          agentSprite.sprite.y - 20,
        );
        // Bob animation
        agentSprite.alertIcon.y +=
          Math.sin(updateTime / 300) * 2;
      } else {
        agentSprite.alertIcon.setVisible(false);
      }

      // Status particles (timer-gated) — solarpunk themed
      if (ENABLE_PARTICLES && updateTime - agentSprite.lastParticleTime > 2000) {
        if (agentSprite.agentStatus === 'working' && this.textures.exists('particle-glint')) {
          // Working: gold solar glint particles
          agentSprite.lastParticleTime = updateTime;
          const sparkle = this.add.particles(agentSprite.sprite.x, agentSprite.sprite.y - 8, 'particle-glint', {
            speed: { min: 10, max: 30 },
            angle: { min: 230, max: 310 },
            lifespan: 600,
            alpha: { start: 0.7, end: 0 },
            tint: 0xf6d55c,
            scale: { start: 1, end: 0.3 },
            emitting: false,
          });
          sparkle.setDepth(6);
          sparkle.emitParticle(2);
          this.time.delayedCall(700, () => sparkle.destroy());
        } else if (agentSprite.agentStatus === 'error' && this.textures.exists('particle-spore')) {
          // Error: fading spore particles (wilting effect)
          agentSprite.lastParticleTime = updateTime;
          const wisps = this.add.particles(agentSprite.sprite.x, agentSprite.sprite.y, 'particle-spore', {
            speed: { min: 5, max: 15 },
            angle: { min: 250, max: 290 },
            lifespan: 800,
            alpha: { start: 0.4, end: 0 },
            tint: 0xef4444,
            scale: { start: 0.8, end: 0.2 },
            emitting: false,
          });
          wisps.setDepth(6);
          wisps.emitParticle(3);
          this.time.delayedCall(900, () => wisps.destroy());
        }
      }
    });
  }

  shutdown(): void {
    if (this.stateCleanup) {
      this.stateCleanup();
      this.stateCleanup = null;
    }
    if (this.sessionIdCleanup) {
      this.sessionIdCleanup();
      this.sessionIdCleanup = null;
    }
    if (this.emoteCleanup) {
      this.emoteCleanup();
      this.emoteCleanup = null;
    }
    if (this.emotePickerCleanup) {
      this.emotePickerCleanup();
      this.emotePickerCleanup = null;
    }
    if (this.avatarConfigCleanup) {
      this.avatarConfigCleanup();
      this.avatarConfigCleanup = null;
    }
    if (this.zoneEnterCleanup) {
      this.zoneEnterCleanup();
      this.zoneEnterCleanup = null;
    }
    if (this.zoneLeaveCleanup) {
      this.zoneLeaveCleanup();
      this.zoneLeaveCleanup = null;
    }
    if (this.walkToEntityCleanup) {
      this.walkToEntityCleanup();
      this.walkToEntityCleanup = null;
    }
    this.pendingArrivalAction = null;
    if (this.interactableManager) {
      this.interactableManager.destroy();
      this.interactableManager = null;
    }
    if (this.scriptBridge) {
      this.scriptBridge.destroy();
      this.scriptBridge = null;
    }
    if (this.tileAnimTimer) {
      this.tileAnimTimer.destroy();
      this.tileAnimTimer = null;
    }
    this.animatedTileOverlays = [];
    if (this.virtualJoystick) {
      this.virtualJoystick.destroy();
      this.virtualJoystick = null;
    }
    if (this.touchButtons) {
      this.touchButtons.destroy();
      this.touchButtons = null;
    }
    this.clickPath = [];
    this.clickPathIndex = 0;
    this.pathfinder = null;
    if (this.clickMarker) {
      this.clickMarker.destroy();
      this.clickMarker = null;
    }
    this.followTarget = null;
    if (this.followLabel) {
      this.followLabel.destroy();
      this.followLabel = null;
    }
    this.explorerMode = false;
    // Clean up companion sprites
    this.companionSprites.forEach((rect) => rect.destroy());
    this.companionSprites.clear();
    // Clear tactician reference so update() short-circuits if a frame fires
    // after shutdown but before the scene is fully torn down.
    this.tactician = undefined;
  }

  private createAnimations(): void {
    // Tactician animations — 4 directions × 3 walk frames
    // Spritesheet layout: frames 0-2 = down, 3-5 = left, 6-8 = up, 9-11 = right
    // Walk cycle uses classic JRPG 1-2-1-3 pattern (stand, walkL, stand, walkR)
    const hasTacticianSheet = this.textures.exists('tactician') &&
      this.textures.get('tactician').frameTotal > 1;

    if (hasTacticianSheet) {
      createAvatarAnimations(this, 'tactician');
    }

    // Agent animations — 2 frames each (idle + working)
    for (const role of AGENT_ROLES) {
      const key = `agent-${role}`;
      const hasSheet = this.textures.exists(key) &&
        this.textures.get(key).frameTotal > 1;

      if (hasSheet) {
        this.anims.create({
          key: `${key}-idle`,
          frames: [{ key, frame: 0 }],
          frameRate: 1,
          repeat: 0,
        });

        this.anims.create({
          key: `${key}-working`,
          frames: this.anims.generateFrameNumbers(key, { start: 0, end: 1 }),
          frameRate: 3,
          repeat: -1,
        });
      }
    }
  }

  private createFloor(): void {
    // Procedural fallback only paints LEGACY_FLOOR_EXTENT (1280x720). This
    // intentionally disagrees with worldWidth/Height (1600x896) — the Tiled
    // map fills the larger extent; this fallback preserves the pre-50x28
    // legacy footprint when no map is loaded. See ../constants.ts for notes.
    const { width: floorW, height: floorH } = LEGACY_FLOOR_EXTENT;
    for (let x = 0; x < floorW; x += TILE_SIZE) {
      for (let y = 0; y < floorH; y += TILE_SIZE) {
        const textureKey = this.textures.exists('floor-tile') ? 'floor-tile' : 'office-tileset';
        this.add.image(x + TILE_SIZE / 2, y + TILE_SIZE / 2, textureKey, 0).setAlpha(0.5);
      }
    }

    // Draw grid lines for visual structure
    const graphics = this.add.graphics();
    graphics.lineStyle(1, 0x334155, 0.3);
    for (let x = 0; x <= floorW; x += TILE_SIZE) {
      graphics.lineBetween(x, 0, x, floorH);
    }
    for (let y = 0; y <= floorH; y += TILE_SIZE) {
      graphics.lineBetween(0, y, floorW, y);
    }
  }

  private createDepartmentZones(): void {
    const zoneKeys: Record<string, string> = {
      engineering: 'zone-engineering',
      sales: 'zone-sales',
      support: 'zone-support',
      research: 'zone-research',
    };

    // Per-department ambient lighting (solarpunk tints)
    const DEPT_LIGHTING: Record<string, { color: number; alpha: number }> = {
      engineering: { color: 0x9b59b6, alpha: 0.06 },  // Subtle purple grow-light tint
      research:    { color: 0x2d8a6e, alpha: 0.05 },  // Cool teal-green (library)
      sales:       { color: 0xf6d55c, alpha: 0.04 },  // Warm golden cafe light
      crm:         { color: 0xf6d55c, alpha: 0.04 },  // Warm golden cafe light
      support:     { color: 0x4a9e6e, alpha: 0.05 },  // Zen green wash
    };

    Object.entries(DEPARTMENT_LAYOUT).forEach(([slug, layout], index) => {
      const textureKey = zoneKeys[slug] ?? 'zone-engineering';
      const zone = this.add
        .image(layout.x, layout.y, textureKey)
        .setOrigin(0, 0)
        .setAlpha(0.2);
      this.departmentZones.push(zone);

      // Ambient breathing pulse on zone overlays (subtle FFVI-style tint)
      this.tweens.add({
        targets: zone,
        alpha: { from: 0.08, to: 0.15 },
        duration: 4000 + index * 600,
        yoyo: true,
        repeat: -1,
        ease: 'Sine.easeInOut',
      });

      // Solarpunk department ambient lighting overlay (ADD blend for glow)
      const deptLight = DEPT_LIGHTING[slug];
      if (deptLight) {
        const zoneOvW = layout.w ?? 640;
        const zoneOvH = layout.h ?? 320;
        const lightOverlay = this.add.rectangle(
          layout.x + zoneOvW / 2, layout.y + zoneOvH / 2,
          zoneOvW, zoneOvH,
          deptLight.color, deptLight.alpha,
        );
        lightOverlay.setBlendMode(Phaser.BlendModes.ADD);
        lightOverlay.setDepth(1); // Above floor, below sprites
      }

      // Department label (centered in zone)
      const zoneW = layout.w ?? 640;
      const zoneH = layout.h ?? 320;
      this.add
        .text(layout.x + zoneW / 2, layout.y + 8, layout.label, {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: responsiveFontSize(10),
          color: '#94a3b8',
        })
        .setOrigin(0.5, 0);

      // Review station for each department (placed near center-right of zone)
      const stationX = layout.x + zoneW * 0.75;
      const stationY = layout.y + zoneH * 0.6;
      const stationTexture = this.textures.exists('review-station') ? 'review-station' : 'office-tileset';
      const station = this.add.image(stationX, stationY, stationTexture, stationTexture === 'office-tileset' ? 7 : 0);
      this.reviewStations.set(slug, station);

      // Station label
      this.add
        .text(stationX, stationY + 20, 'REVIEW', {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: '6px',
          color: '#fbbf24',
        })
        .setOrigin(0.5, 0);
    });
  }

  private createTactician(): void {
    // Use map-defined spawn point, or fall back to DEFAULT_SPAWN (lobby centre,
    // col 13 / row 15 of the 50x28 map).
    let spawnX: number = DEFAULT_SPAWN.x;
    let spawnY: number = DEFAULT_SPAWN.y;
    if (this.spawnPoints.length > 0) {
      const sp = this.spawnPoints[0]!;
      spawnX = sp.x;
      spawnY = sp.y;
    }
    // Validate spawn is walkable — nudge down if on a wall tile
    if (this.collisionLayer) {
      const tileSize = 32;
      const tileX = Math.floor(spawnX / tileSize);
      const tileY = Math.floor(spawnY / tileSize);
      const tile = this.collisionLayer.getTileAt(tileX, tileY);
      if (tile) {
        // Blocked — try one tile down
        spawnY += tileSize;
      }
    }

    // If avatar config exists, generate the multi-frame spritesheet and use it
    let initialTexture = 'tactician';
    if (this.localAvatarConfig) {
      const avatarKey = compositeAvatar(this, this.localAvatarConfig);
      createAvatarAnimations(this, avatarKey);
      initialTexture = avatarKey;
      this.localTextureKey = avatarKey;
    }

    this.tactician = this.add.sprite(spawnX, spawnY, initialTexture).setDepth(10).setAlpha(0).setScale(0.5);

    // Play initial idle animation if available
    const idleKey = `${this.localTextureKey}-idle-down`;
    if (this.anims.exists(idleKey)) {
      this.tactician.play(idleKey);
    }

    // Spawn-in effect: scale up with overshoot + fade in
    this.tweens.add({
      targets: this.tactician,
      scaleX: { from: 0.5, to: 1 },
      scaleY: { from: 0.5, to: 1 },
      alpha: { from: 0, to: 1 },
      duration: 400,
      ease: 'Back.easeOut',
    });

    // Solarpunk leaf + sparkle burst at spawn
    if (ENABLE_PARTICLES && this.textures.exists('particle-leaf')) {
      const leafBurst = this.add.particles(spawnX, spawnY, 'particle-leaf', {
        speed: { min: 15, max: 45 },
        angle: { min: 0, max: 360 },
        lifespan: 700,
        alpha: { start: 0.6, end: 0 },
        tint: 0x4a9e6e,
        rotate: { min: 0, max: 360 },
        scale: { start: 1.5, end: 0.5 },
        emitting: false,
      });
      leafBurst.setDepth(11);
      leafBurst.emitParticle(6);
      this.time.delayedCall(800, () => leafBurst.destroy());
    }
    if (ENABLE_PARTICLES && this.textures.exists('particle-sparkle')) {
      const sparkleBurst = this.add.particles(spawnX, spawnY, 'particle-sparkle', {
        speed: { min: 30, max: 70 },
        angle: { min: 0, max: 360 },
        lifespan: 400,
        alpha: { start: 0.8, end: 0 },
        tint: 0xf6d55c,
        scale: { start: 1, end: 0.3 },
        emitting: false,
        blendMode: 'ADD',
      });
      sparkleBurst.setDepth(11);
      sparkleBurst.emitParticle(4);
      this.time.delayedCall(500, () => sparkleBurst.destroy());
    }

    this.cameras.main.startFollow(this.tactician, true, 0.08, 0.08);
    this.cameras.main.setBounds(0, 0, this.worldWidth, this.worldHeight);

    // Click-to-move: pathfinder setup
    this.pathfinder = new Pathfinder(this.collisionLayer, this.worldWidth, this.worldHeight);

    // Click-to-move: pointer handler
    this.input.on('pointerup', (pointer: Phaser.Input.Pointer) => {
      // Ignore if UI is focused or help overlay visible
      if (this.gamepadManager.isFocused() || this.helpOverlay.visible) return;
      // Only left click
      if (pointer.button !== 0) return;
      if (!this.tactician) return;

      const worldX = pointer.worldX;
      const worldY = pointer.worldY;

      if (this.pathfinder) {
        this.clickPath = this.pathfinder.findPath(
          this.tactician.x,
          this.tactician.y,
          worldX,
          worldY,
        );
        this.clickPathIndex = 0;
      } else {
        this.clickPath = [{ x: worldX, y: worldY }];
        this.clickPathIndex = 0;
      }

      // Visual marker at destination
      if (this.clickMarker) this.clickMarker.destroy();
      this.clickMarker = this.add.circle(worldX, worldY, 6, 0x6366f1, 0.5).setDepth(15);
      this.tweens.add({
        targets: this.clickMarker,
        alpha: 0,
        scale: 2,
        duration: 800,
        onComplete: () => {
          this.clickMarker?.destroy();
          this.clickMarker = null;
        },
      });
    });

    // Label above tactician
    this.tacticianLabel = this.add
      .text(spawnX, spawnY - 24, 'YOU', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#a5b4fc',
      })
      .setOrigin(0.5)
      .setDepth(10);
  }

  private createHelpOverlay(): void {
    this.helpOverlay = this.add.container(640, 360).setDepth(100).setVisible(false);

    // Semi-transparent backdrop
    const backdrop = this.add.rectangle(0, 0, 1280, 720, 0x000000, 0.5);
    const bg = this.add.rectangle(0, 0, 420, 420, 0x0f172a, 0.95);

    const title = this.add
      .text(0, -140, 'KEYBOARD SHORTCUTS', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '10px',
        color: '#a5b4fc',
      })
      .setOrigin(0.5);

    const shortcuts = [
      'WASD / Arrows     Move',
      'Click             Click-to-Move',
      'ENTER / A (pad)   Approve',
      'ESC / B (pad)     Deny / Cancel',
      'E / X (pad)       Inspect / Interact',
      'F                 Follow Nearest Player',
      'Tab               Explorer Mode',
      'T or /            Chat',
      'R                 Emotes (1-9)',
      'M / V             Mic / Camera',
      '?                 Toggle Help',
    ];

    const lines = shortcuts.map((text, i) =>
      this.add.text(-180, -90 + i * 28, text, {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '7px',
        color: '#cbd5e1',
      }),
    );

    // Close button
    const closeBtn = this.add
      .text(180, -140, '[X]', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#f87171',
      })
      .setOrigin(0.5)
      .setInteractive({ useHandCursor: true })
      .on('pointerdown', () => this.helpOverlay.setVisible(false));

    this.helpOverlay.add([backdrop, bg, title, ...lines, closeBtn]);

    // Make it scroll-fixed so it stays centered on screen
    this.helpOverlay.setScrollFactor(0);
  }

  private onStateUpdate(state: OfficeState): void {
    this.officeState = state;

    // Update local session ID if available
    if (state.localSessionId) {
      this.localSessionId = state.localSessionId;
    }

    // Reconcile remote player sprites
    this.reconcileRemotePlayers(state.players ?? []);

    // Reconcile local player companion
    if (state.players && this.localSessionId && this.tactician) {
      const localPlayer = state.players.find((p: Player) => p.sessionId === this.localSessionId);
      if (localPlayer) {
        this.reconcileCompanionSprite(
          this.localSessionId,
          localPlayer.companionType,
          this.tactician.x,
          this.tactician.y,
        );
      }
    }

    // Reconcile agent sprites with current state
    const currentAgentIds = new Set<string>();

    state.departments.forEach((dept: Department) => {
      if (dept.agents) {
        dept.agents.forEach((agent: Agent) => {
          currentAgentIds.add(agent.id);
          this.updateOrCreateAgentSprite(agent, dept);
        });
      }
    });

    // Remove sprites for agents no longer in state
    this.agentSprites.forEach((agentSprite, agentId) => {
      if (!currentAgentIds.has(agentId)) {
        agentSprite.sprite.destroy();
        agentSprite.alertIcon.destroy();
        agentSprite.statusHalo.destroy();
        agentSprite.nameBackground.destroy();
        if (agentSprite.breathingTween) agentSprite.breathingTween.stop();
        if (agentSprite.haloTween) agentSprite.haloTween.stop();
        this.agentBehavior.removeAgent(agentId);
        this.agentSprites.delete(agentId);
      }
    });

    // Apply desk positions as agent home positions
    if (this.interactableManager) {
      const deskPositions = this.interactableManager.getDeskPositions();
      deskPositions.forEach((pos, agentId) => {
        this.agentBehavior.setDeskPosition(agentId, pos.x, pos.y);
      });
    }

    // Update review station pending counts with glow
    if (state.reviewStations) {
      state.reviewStations.forEach((station: ReviewStation) => {
        const stationSprite = this.reviewStations.get(station.departmentId);
        if (stationSprite) {
          const hasPending = station.pendingApprovals > 0;
          stationSprite.setAlpha(hasPending ? 1 : 0.5);

          // Pulsing glow when approvals pending
          const tweenKey = `station-pulse-${station.departmentId}`;
          const existingTween = this.tweens.getTweensOf(stationSprite);
          if (hasPending && existingTween.length === 0) {
            this.tweens.add({
              targets: stationSprite,
              alpha: { from: 0.6, to: 1.0 },
              duration: 800,
              yoyo: true,
              repeat: -1,
              ease: 'Sine.easeInOut',
            });
            if (stationSprite.preFX) {
              stationSprite.preFX.addGlow(0xfbbf24, 2);
            }
          } else if (!hasPending && existingTween.length > 0) {
            this.tweens.killTweensOf(stationSprite);
            stationSprite.setAlpha(0.5);
            if (stationSprite.preFX) {
              stationSprite.preFX.clear();
            }
          }
        }
      });
    }
  }

  private getPlayerStatusColor(status?: string): number {
    switch (status) {
      case 'online': return 0x10b981;
      case 'away': return 0xfbbf24;
      case 'busy': return 0xef4444;
      case 'dnd': return 0x64748b;
      default: return 0x10b981;
    }
  }

  private reconcileRemotePlayers(players: Player[]): void {
    const currentSessionIds = new Set<string>();

    for (const player of players) {
      // Skip local player
      if (player.sessionId === this.localSessionId) continue;
      currentSessionIds.add(player.sessionId);

      const existing = this.remotePlayers.get(player.sessionId);
      if (existing) {
        // Update target position for interpolation
        existing.targetX = player.x;
        existing.targetY = player.y;
        existing.direction = player.direction;
        existing.label.setText(player.name);
        // Update status dot color
        existing.statusDot.setFillStyle(this.getPlayerStatusColor(player.playerStatus));
        // Update music status label
        this.reconcileMusicLabel(existing, player.musicStatus);
        // Update companion sprite
        this.reconcileCompanionSprite(player.sessionId, player.companionType, player.x, player.y);
        // Update avatar texture if config changed
        if (player.avatarConfig) {
          try {
            const cfg = JSON.parse(player.avatarConfig) as AvatarConfig;
            const key = compositeAvatar(this, cfg);
            if (existing.sprite.texture.key !== key) {
              existing.sprite.setTexture(key);
              createAvatarAnimations(this, key);
              existing.textureKey = key;
            }
          } catch { /* ignore bad config */ }
        }
      } else {
        // Create new remote player sprite (use avatar texture if available)
        let remoteTexture = 'tactician';
        if (player.avatarConfig) {
          try {
            const cfg = JSON.parse(player.avatarConfig) as AvatarConfig;
            remoteTexture = compositeAvatar(this, cfg);
          } catch { /* ignore */ }
        }
        // Register per-texture walk/idle animations for this remote player
        createAvatarAnimations(this, remoteTexture);
        const sprite = this.add.sprite(player.x, player.y, remoteTexture).setDepth(9).setAlpha(0.85);
        const remoteIdleKey = `${remoteTexture}-idle-down`;
        if (this.anims.exists(remoteIdleKey)) {
          sprite.play(remoteIdleKey);
        }

        const label = this.add
          .text(player.x, player.y - 24, player.name, {
            fontFamily: '"Press Start 2P", monospace',
            fontSize: '7px',
            color: '#86efac',
          })
          .setOrigin(0.5)
          .setDepth(9);

        const statusDotColor = this.getPlayerStatusColor(player.playerStatus);
        const statusDot = this.add.circle(player.x - 20, player.y - 24, 3, statusDotColor, 1).setDepth(9);

        // Music status label (below name)
        let musicLabel: Phaser.GameObjects.Text | null = null;
        if (player.musicStatus) {
          musicLabel = this.add
            .text(player.x, player.y - 16, player.musicStatus, {
              fontFamily: '"Press Start 2P", monospace',
              fontSize: '6px',
              color: '#94a3b8',
            })
            .setOrigin(0.5)
            .setDepth(9);
        }

        this.remotePlayers.set(player.sessionId, {
          sprite,
          label,
          statusDot,
          musicLabel,
          targetX: player.x,
          targetY: player.y,
          direction: player.direction,
          textureKey: remoteTexture,
        });

        // Create companion sprite if player has one
        this.reconcileCompanionSprite(player.sessionId, player.companionType, player.x, player.y);
      }
    }

    // Remove sprites for disconnected players
    this.remotePlayers.forEach((remote, sessionId) => {
      if (!currentSessionIds.has(sessionId)) {
        remote.sprite.destroy();
        remote.label.destroy();
        remote.statusDot.destroy();
        remote.musicLabel?.destroy();
        this.remotePlayers.delete(sessionId);
        // Clean up companion
        const companionSprite = this.companionSprites.get(sessionId);
        if (companionSprite) {
          companionSprite.destroy();
          this.companionSprites.delete(sessionId);
        }
        this.companionBehavior.removeCompanion(sessionId);
      }
    });
  }

  /**
   * Create, update, or remove the music status label beneath a remote player's name.
   */
  private reconcileMusicLabel(remote: RemotePlayerSprite, musicStatus: string | undefined): void {
    const text = musicStatus ?? '';
    if (text) {
      if (remote.musicLabel) {
        remote.musicLabel.setText(text);
      } else {
        remote.musicLabel = this.add
          .text(remote.sprite.x, remote.sprite.y - 16, text, {
            fontFamily: '"Press Start 2P", monospace',
            fontSize: '6px',
            color: '#94a3b8',
          })
          .setOrigin(0.5)
          .setDepth(9);
      }
    } else if (remote.musicLabel) {
      remote.musicLabel.destroy();
      remote.musicLabel = null;
    }
  }

  /**
   * Create, update, or remove a companion sprite for a given player session.
   * Uses simple colored rectangles (8x8) as companion visuals.
   */
  private reconcileCompanionSprite(
    sessionId: string,
    companionType: string | undefined,
    ownerX: number,
    ownerY: number,
  ): void {
    const existing = this.companionSprites.get(sessionId);

    if (!companionType || !COMPANION_COLORS[companionType]) {
      // Remove companion if type is empty or invalid
      if (existing) {
        existing.destroy();
        this.companionSprites.delete(sessionId);
        this.companionBehavior.removeCompanion(sessionId);
      }
      return;
    }

    if (existing) {
      // Update color if companion type changed
      const color = COMPANION_COLORS[companionType];
      existing.setFillStyle(color);
    } else {
      // Create new companion sprite
      const color = COMPANION_COLORS[companionType];
      const rect = this.add.rectangle(ownerX, ownerY + 28, 8, 8, color)
        .setDepth(8)
        .setAlpha(0.9);
      this.companionSprites.set(sessionId, rect);
      this.companionBehavior.initCompanion(sessionId, ownerX, ownerY);
    }
  }

  private updateOrCreateAgentSprite(agent: Agent, dept: Department): void {
    const textureKey = `agent-${agent.role}`;
    const layout = this.departmentLayouts.get(dept.slug);
    if (!layout) return;

    const existing = this.agentSprites.get(agent.id);
    const hasPending = agent.status === 'waiting_approval';

    if (existing) {
      // Update existing sprite state
      existing.hasPendingApproval = hasPending;

      // Update status halo color + pulse
      if (existing.agentStatus !== agent.status) {
        existing.agentStatus = agent.status;
        // Notify behavior system of status change
        this.agentBehavior.initAgent(agent.id, existing.sprite.x, existing.sprite.y, agent.status);
        const haloStyle = this.getHaloStyle(agent.status);
        existing.statusHalo.setFillStyle(haloStyle.color, haloStyle.alpha);

        // Manage breathing tween
        if (agent.status === 'idle' && !existing.breathingTween) {
          existing.breathingTween = this.tweens.add({
            targets: existing.sprite,
            scaleY: { from: 1.0, to: 1.04 },
            duration: 2000,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut',
          });
        } else if (agent.status !== 'idle' && existing.breathingTween) {
          existing.breathingTween.stop();
          existing.sprite.setScale(1);
          existing.breathingTween = null;
        }

        // Pulse halo for waiting_approval
        if (existing.haloTween) {
          existing.haloTween.stop();
          existing.haloTween = null;
        }
        if (agent.status === 'waiting_approval') {
          existing.haloTween = this.tweens.add({
            targets: existing.statusHalo,
            alpha: { from: 0.2, to: 0.5 },
            duration: 800,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut',
          });
        }
      }

      // Play status-based animation if available
      const animKey = agent.status === 'working'
        ? `${textureKey}-working`
        : `${textureKey}-idle`;
      if (this.anims.exists(animKey) && existing.sprite.anims.currentAnim?.key !== animKey) {
        existing.sprite.play(animKey);
      }

      // Update currentNodeId label
      const currentNodeId = (agent as unknown as Record<string, unknown>).currentNodeId as string | undefined;
      this.updateNodeLabel(existing, currentNodeId ?? '');

      return;
    }

    // Calculate position within department zone with some offset.
    // SPAWN_OFFSET = inset from zone edge; SPAWN_GRID_SPACING = gap between agents.
    const agentIndex = dept.agents.indexOf(agent);
    const col = agentIndex % 3;
    const row = Math.floor(agentIndex / 3);
    const spriteX = layout.x + SPAWN_OFFSET + col * SPAWN_GRID_SPACING;
    const spriteY = layout.y + SPAWN_OFFSET + row * SPAWN_GRID_SPACING;

    // Status halo beneath agent
    const haloStyle = this.getHaloStyle(agent.status);
    const statusHalo = this.add.circle(spriteX, spriteY + 4, 14, haloStyle.color, haloStyle.alpha).setDepth(4);

    const sprite = this.add.sprite(spriteX, spriteY, textureKey).setDepth(5);

    // Play initial animation
    const initialAnim = agent.status === 'working'
      ? `${textureKey}-working`
      : `${textureKey}-idle`;
    if (this.anims.exists(initialAnim)) {
      sprite.play(initialAnim);
    }

    const alertIcon = this.add
      .image(spriteX + 12, spriteY - 20, 'icon-alert')
      .setDepth(15)
      .setVisible(false);

    // Agent name label with background for readability
    const nameText = agent.name.substring(0, 8);
    const nameLabel = this.add
      .text(spriteX, spriteY + 20, nameText, {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '6px',
        color: '#cbd5e1',
      })
      .setOrigin(0.5, 0)
      .setDepth(6);
    const nameBackground = this.add
      .rectangle(spriteX, spriteY + 23, nameLabel.width + 4, nameLabel.height + 2, 0x000000, 0.5)
      .setDepth(5);

    // Skill badges (small text below agent name)
    const skills = (agent as { skills?: string[] }).skills;
    if (skills && skills.length > 0) {
      const badgeText = skills.slice(0, 2).join(', ');
      this.add
        .text(spriteX, spriteY + 30, badgeText, {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: '4px',
          color: '#94a3b8',
        })
        .setOrigin(0.5, 0)
        .setDepth(5);
    }

    // Idle breathing tween
    let breathingTween: Phaser.Tweens.Tween | null = null;
    if (agent.status === 'idle') {
      breathingTween = this.tweens.add({
        targets: sprite,
        scaleY: { from: 1.0, to: 1.04 },
        duration: 2000,
        yoyo: true,
        repeat: -1,
        ease: 'Sine.easeInOut',
      });
    }

    // Pulse halo for waiting_approval
    let haloTween: Phaser.Tweens.Tween | null = null;
    if (agent.status === 'waiting_approval') {
      haloTween = this.tweens.add({
        targets: statusHalo,
        alpha: { from: 0.2, to: 0.5 },
        duration: 800,
        yoyo: true,
        repeat: -1,
        ease: 'Sine.easeInOut',
      });
    }

    this.agentSprites.set(agent.id, {
      sprite,
      alertIcon,
      statusHalo,
      nameLabel,
      nameBackground,
      nodeLabel: null,
      nodeLabelBackground: null,
      agentId: agent.id,
      agentStatus: agent.status,
      hasPendingApproval: hasPending,
      breathingTween,
      haloTween,
      lastParticleTime: 0,
    });

    // Initialize movement behavior
    this.agentBehavior.initAgent(agent.id, spriteX, spriteY, agent.status);
  }

  private updateNodeLabel(agentSprite: AgentSprite, currentNodeId: string): void {
    if (currentNodeId) {
      const x = agentSprite.sprite.x;
      const y = agentSprite.nameLabel.y + agentSprite.nameLabel.height + 4;
      if (!agentSprite.nodeLabel) {
        agentSprite.nodeLabel = this.add
          .text(x, y, `[${currentNodeId}]`, {
            fontFamily: '"Press Start 2P", monospace',
            fontSize: '5px',
            color: '#22d3ee',
          })
          .setOrigin(0.5, 0)
          .setDepth(6);
        agentSprite.nodeLabelBackground = this.add
          .rectangle(x, y + 4, agentSprite.nodeLabel.width + 4, agentSprite.nodeLabel.height + 2, 0x000000, 0.6)
          .setDepth(5);
      } else {
        agentSprite.nodeLabel.setText(`[${currentNodeId}]`).setPosition(x, y).setVisible(true);
        agentSprite.nodeLabelBackground
          ?.setPosition(x, y + 4)
          .setSize(agentSprite.nodeLabel.width + 4, agentSprite.nodeLabel.height + 2)
          .setVisible(true);
      }
    } else {
      agentSprite.nodeLabel?.setVisible(false);
      agentSprite.nodeLabelBackground?.setVisible(false);
    }
  }

  private getHaloStyle(status: string): { color: number; alpha: number } {
    // Solarpunk status colors
    switch (status) {
      case 'working': return { color: 0xf6d55c, alpha: 0.25 };         // Solar gold
      case 'waiting_approval': return { color: 0xd4a43a, alpha: 0.35 }; // Deep amber
      case 'paused': return { color: 0x8b7355, alpha: 0.15 };           // Wood tone
      case 'error': return { color: 0xb91c1c, alpha: 0.3 };             // Deep red
      default: return { color: 0x4a9e6e, alpha: 0.15 };                 // Soft moss green (idle)
    }
  }

  /**
   * Apply animation hints from the AgentBehavior system to agent sprites.
   * Triggers one-shot tweens for look/stretch/sway and continuous effects
   * for head-bob and error dimming.
   */
  private applyAnimationHint(agentSprite: AgentSprite, hint: AnimationHint): void {
    const sprite = agentSprite.sprite;

    // Idle looking: briefly face a direction then return
    if (hint.lookDirection) {
      const textureKey = `agent-${(agentSprite as { agentRole?: string }).agentRole || 'coder'}`;
      const lookAnim = `${textureKey}-idle`;
      if (this.anims.exists(lookAnim)) {
        sprite.setFlipX(hint.lookDirection === 'left');
        this.time.delayedCall(1500, () => {
          sprite.setFlipX(false);
        });
      }
    }

    // Idle stretching: quick scaleY tween
    if (hint.stretch) {
      this.tweens.add({
        targets: sprite,
        scaleY: 1.06,
        duration: 600,
        yoyo: true,
        ease: 'Sine.easeInOut',
      });
    }

    // Working head-bob: subtle scaleX oscillation
    if (hint.headBobPhase !== undefined) {
      const bobScale = 1.0 + Math.sin(hint.headBobPhase * Math.PI * 2) * 0.015;
      sprite.setScale(bobScale, sprite.scaleY);
    }

    // Waiting-approval sway: offset sprite X slightly
    if (hint.swayOffset !== undefined) {
      sprite.x += hint.swayOffset;
    }

    // Error dimming: reduce alpha and apply red tint
    if (hint.errorDim) {
      sprite.setAlpha(0.7);
      sprite.setTint(0xffaaaa);
    } else if (sprite.alpha < 1 && agentSprite.agentStatus !== 'error') {
      // Restore when no longer in error state
      sprite.setAlpha(1);
      sprite.clearTint();
    }
  }

  private findAgentDepartmentSlug(agentId: string): string | null {
    if (!this.officeState) return null;
    for (const dept of this.officeState.departments) {
      if (dept.agents?.some((a: Agent) => a.id === agentId)) {
        return dept.slug;
      }
    }
    return null;
  }

  private updateLocalAvatarTexture(): void {
    if (!this.localAvatarConfig || !this.tactician) return;
    const textureKey = compositeAvatar(this, this.localAvatarConfig);
    createAvatarAnimations(this, textureKey);
    this.localTextureKey = textureKey;
    this.tactician.setTexture(textureKey);
    // Play idle animation for current direction with new texture
    const idleKey = `${textureKey}-idle-${this.lastDirection}`;
    if (this.anims.exists(idleKey)) {
      this.tactician.play(idleKey);
    }
  }

  private showEmoteBubble(sessionId: string, emoteType: string): void {
    const frameIndex = EMOTE_FRAME_MAP[emoteType];
    if (frameIndex === undefined) return;

    // Find the sprite to attach the emote to
    let targetX: number;
    let targetY: number;

    if (sessionId === this.localSessionId) {
      if (!this.tactician) return;
      targetX = this.tactician.x;
      targetY = this.tactician.y;
    } else {
      const remote = this.remotePlayers.get(sessionId);
      if (!remote) return;
      targetX = remote.sprite.x;
      targetY = remote.sprite.y;
    }

    const hasEmoteSheet = this.textures.exists('emotes') &&
      this.textures.get('emotes').frameTotal > 1;

    if (hasEmoteSheet) {
      const emoteSprite = this.add.sprite(targetX, targetY - 32, 'emotes', frameIndex)
        .setDepth(20)
        .setScale(0.3);

      // Scale-up + float-up + fade-out tween
      this.tweens.add({
        targets: emoteSprite,
        scaleX: 1.2,
        scaleY: 1.2,
        y: targetY - 56,
        alpha: { from: 1, to: 0 },
        duration: EMOTE_DURATION_MS,
        ease: 'Cubic.easeOut',
        onComplete: () => emoteSprite.destroy(),
      });
    } else {
      // Fallback: text-based emote
      const EMOTE_TEXT: Record<string, string> = {
        wave: '\u{1F44B}', thumbsup: '\u{1F44D}', heart: '\u{2764}',
        laugh: '\u{1F602}', think: '\u{1F914}', clap: '\u{1F44F}',
        fire: '\u{1F525}', sparkle: '\u{2728}', coffee: '\u{2615}',
      };
      const emoteText = this.add.text(targetX, targetY - 32, EMOTE_TEXT[emoteType] ?? '?', {
        fontSize: '20px',
      }).setOrigin(0.5).setDepth(20);

      this.tweens.add({
        targets: emoteText,
        y: targetY - 56,
        alpha: { from: 1, to: 0 },
        duration: EMOTE_DURATION_MS,
        ease: 'Cubic.easeOut',
        onComplete: () => emoteText.destroy(),
      });
    }
  }

  private handleProximityInteraction(action: 'approve' | 'inspect'): void {
    if (!this.tactician) return;
    // Find the nearest agent with a pending approval within proximity
    let nearestAgentId: string | null = null;
    let nearestDist = PROXIMITY_THRESHOLD;
    const tactician = this.tactician;

    this.agentSprites.forEach((agentSprite) => {
      if (!agentSprite.hasPendingApproval) return;

      const dist = Phaser.Math.Distance.Between(
        tactician.x,
        tactician.y,
        agentSprite.sprite.x,
        agentSprite.sprite.y,
      );

      if (dist < nearestDist) {
        nearestDist = dist;
        nearestAgentId = agentSprite.agentId;
      }
    });

    if (nearestAgentId) {
      // Flash the agent sprite for feedback
      const agentEntry = this.agentSprites.get(nearestAgentId);
      if (agentEntry) {
        this.tweens.add({
          targets: agentEntry.sprite,
          alpha: 0.5,
          yoyo: true,
          duration: 150,
          repeat: 1,
        });
      }

      if (action === 'approve') {
        gameEventBus.emit('approval-open', nearestAgentId);
      }
    }
  }

  // === Wave -> Walk Over (E1 roster/person-card action) ===

  /**
   * Path the local avatar to a walkable tile next to the target (remote
   * player or agent-citizen), then wave on arrival. Reuses the click-to-move
   * path follower in update() — a walk-to-entity command is just a
   * server-resolved click destination.
   */
  private handleWalkToEntity(detail: { kind: 'player' | 'agent'; id: string; seq: number }): void {
    if (!detail || typeof detail.seq !== 'number') return;
    // Guard against the event bus replaying a stale cached command to a
    // scene that (re)subscribes after the command was originally issued.
    if (detail.seq <= this.lastWalkToSeq) return;
    this.lastWalkToSeq = detail.seq;

    if (!this.tactician || !this.pathfinder) return;

    const targetSprite =
      detail.kind === 'player'
        ? this.remotePlayers.get(detail.id)?.sprite
        : this.agentSprites.get(detail.id)?.sprite;
    if (!targetSprite) return;

    this.clickPath = this.pathfinder.findPathAdjacentTo(
      this.tactician.x,
      this.tactician.y,
      targetSprite.x,
      targetSprite.y,
    );
    this.clickPathIndex = 0;

    // Visual marker at the target, mirroring click-to-move feedback.
    if (this.clickMarker) this.clickMarker.destroy();
    this.clickMarker = this.add.circle(targetSprite.x, targetSprite.y, 6, 0x6366f1, 0.5).setDepth(15);
    this.tweens.add({
      targets: this.clickMarker,
      alpha: 0,
      scale: 2,
      duration: 800,
      onComplete: () => {
        if (this.clickMarker) {
          this.clickMarker.destroy();
          this.clickMarker = null;
        }
      },
    });

    this.pendingArrivalAction = () => {
      gameEventBus.emit('send-emote', { type: 'wave' });
    };
  }

  // === Follow Player Camera (PR 1.2) ===

  private toggleFollowNearestPlayer(): void {
    if (this.followTarget) {
      this.cancelFollow();
      return;
    }

    if (!this.tactician) return;
    const tactician = this.tactician;
    // Find nearest remote player
    let nearestId: string | null = null;
    let nearestDist = Infinity;
    this.remotePlayers.forEach((remote, sessionId) => {
      const dist = Phaser.Math.Distance.Between(
        tactician.x, tactician.y,
        remote.sprite.x, remote.sprite.y,
      );
      if (dist < nearestDist) {
        nearestDist = dist;
        nearestId = sessionId;
      }
    });

    if (nearestId) {
      this.startFollow(nearestId);
    }
  }

  private startFollow(sessionId: string): void {
    const remote = this.remotePlayers.get(sessionId);
    if (!remote) return;

    this.followTarget = sessionId;
    this.cameras.main.stopFollow();
    this.cameras.main.startFollow(remote.sprite, true, 0.08, 0.08);

    // Show follow badge
    if (this.followLabel) this.followLabel.destroy();
    this.followLabel = this.add
      .text(this.cameras.main.width / 2, 60, `Following: ${remote.label.text}`, {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#86efac',
        backgroundColor: '#0f172aCC',
        padding: { x: 6, y: 3 },
      })
      .setOrigin(0.5)
      .setScrollFactor(0)
      .setDepth(50);

    gameEventBus.emit('follow-status', { following: true, name: remote.label.text });
  }

  private cancelFollow(): void {
    this.followTarget = null;
    this.cameras.main.stopFollow();
    if (this.tactician) {
      this.cameras.main.startFollow(this.tactician, true, 0.08, 0.08);
    }
    if (this.followLabel) {
      this.followLabel.destroy();
      this.followLabel = null;
    }
    gameEventBus.emit('follow-status', { following: false, name: '' });
  }

  // === Explorer Mode (PR 1.5) ===

  private toggleExplorerMode(): void {
    if (this.explorerMode) {
      this.exitExplorerMode();
    } else {
      this.enterExplorerMode();
    }
  }

  private enterExplorerMode(): void {
    this.explorerMode = true;
    this.explorerPrevZoom = this.cameras.main.zoom;

    // Cancel follow if active
    if (this.followTarget) this.cancelFollow();

    // Zoom out to show full map
    this.cameras.main.stopFollow();
    const zoomX = this.cameras.main.width / this.worldWidth;
    const zoomY = this.cameras.main.height / this.worldHeight;
    const targetZoom = Math.min(zoomX, zoomY) * 0.95;
    this.cameras.main.setZoom(targetZoom);
    this.cameras.main.centerOn(this.worldWidth / 2, this.worldHeight / 2);

    gameEventBus.emit('explorer-mode', true);
  }

  private exitExplorerMode(): void {
    this.explorerMode = false;
    this.cameras.main.setZoom(this.explorerPrevZoom);
    if (this.tactician) {
      this.cameras.main.startFollow(this.tactician, true, 0.08, 0.08);
    }
    gameEventBus.emit('explorer-mode', false);
  }
}
