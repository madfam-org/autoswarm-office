import Phaser from 'phaser';
import { GamepadManager } from '../GamepadManager';
import { gameEventBus } from '../PhaserGame';
import { loadTiledMap } from '../TiledMapLoader';
import type { DepartmentZone } from '../TiledMapLoader';
import { compositeAvatar } from '../AvatarCompositor';
import { VirtualJoystick } from '../VirtualJoystick';
import { TouchActionButtons } from '../TouchActionButtons';
import { InteractableManager } from '../InteractableManager';
import { ScriptBridge } from '../scripting/ScriptBridge';
import { AgentBehavior } from '../AgentBehavior';
import type {
  OfficeState,
  Department,
  ReviewStation,
  Agent,
  Player,
  AvatarConfig,
} from '@autoswarm/shared-types';

const TILE_SIZE = 32;
const TACTICIAN_SPEED = 200;
const PROXIMITY_THRESHOLD = 64;
const MOVE_THROTTLE_MS = 66; // ~15fps
const EMOTE_DURATION_MS = 3000;
const ENABLE_POST_FX = true;
const ENABLE_PARTICLES = true;

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

interface AgentSprite {
  sprite: Phaser.GameObjects.Sprite;
  alertIcon: Phaser.GameObjects.Image;
  statusHalo: Phaser.GameObjects.Arc;
  nameLabel: Phaser.GameObjects.Text;
  nameBackground: Phaser.GameObjects.Rectangle;
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
  targetX: number;
  targetY: number;
  direction: string;
}

/** Department zone layout positions on the office grid (procedural fallback) */
const DEPARTMENT_LAYOUT: Record<string, { x: number; y: number; label: string }> = {
  engineering: { x: 96, y: 80, label: 'ENGINEERING' },
  crm: { x: 480, y: 80, label: 'CRM' },
  support: { x: 96, y: 400, label: 'SUPPORT' },
  research: { x: 480, y: 400, label: 'RESEARCH' },
};

const AGENT_ROLES = ['planner', 'coder', 'reviewer', 'researcher', 'crm', 'support'] as const;

export class OfficeScene extends Phaser.Scene {
  private gamepadManager!: GamepadManager;
  private tactician!: Phaser.GameObjects.Sprite;
  private tacticianLabel!: Phaser.GameObjects.Text;
  private agentSprites: Map<string, AgentSprite> = new Map();
  private remotePlayers: Map<string, RemotePlayerSprite> = new Map();
  private departmentZones: Phaser.GameObjects.Image[] = [];
  private departmentLayouts: Map<string, { x: number; y: number; label: string }> = new Map();
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
  private localAvatarConfig: AvatarConfig | null = null;
  private virtualJoystick: VirtualJoystick | null = null;
  private touchButtons: TouchActionButtons | null = null;
  private interactableManager: InteractableManager | null = null;
  private scriptBridge: ScriptBridge | null = null;
  private isTouchDevice: boolean = false;
  private helpOverlay!: Phaser.GameObjects.Container;
  private lastDirection: string = 'down';
  private lastMoveTime: number = 0;
  private lastSentX: number = 0;
  private lastSentY: number = 0;
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;
  private worldWidth: number = 1280;
  private worldHeight: number = 720;
  private dustEmitter: Phaser.GameObjects.Particles.ParticleEmitter | null = null;
  private ambientEmitter: Phaser.GameObjects.Particles.ParticleEmitter | null = null;
  private agentBehavior: AgentBehavior = new AgentBehavior();

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
    gameEventBus.on('chat-focus', (detail) => {
      this.gamepadManager.setChatFocused(detail as boolean);
    });

    // Listen for emote picker focus
    this.emotePickerCleanup = gameEventBus.on('emote-picker-focus', (detail) => {
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
    this.interactableManager = new InteractableManager(this, this.tactician);
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
      if (event.key === '?') {
        this.helpOverlay.setVisible(!this.helpOverlay.visible);
      }
    });

    // === Post-FX: CRT vignette ===
    if (ENABLE_POST_FX && this.cameras.main.postFX) {
      this.cameras.main.postFX.addVignette(0.5, 0.5, 0.85, 0.25);
    }

    // === Ambient dust particles ===
    if (ENABLE_PARTICLES && this.textures.exists('particle-dot')) {
      this.ambientEmitter = this.add.particles(0, 0, 'particle-dot', {
        x: { min: 0, max: this.worldWidth },
        y: { min: 0, max: this.worldHeight },
        lifespan: 6000,
        frequency: 800,
        alpha: { start: 0, end: 0.3 },
        scale: { start: 0.5, end: 1 },
        speedY: { min: -8, max: -3 },
        speedX: { min: -5, max: 5 },
        blendMode: 'ADD',
      });
      this.ambientEmitter.setDepth(1);
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

    // Populate department layouts from Tiled data, falling back to hardcoded
    if (data.departments.length > 0) {
      for (const dept of data.departments) {
        this.departmentLayouts.set(dept.slug, {
          x: dept.x,
          y: dept.y,
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

    // Load interactables from Tiled object layer (manager created after tactician)
    // Deferred to after createTactician, but we store the tilemap reference
    this._pendingTilemap = data.tilemap;
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
    this.gamepadManager.poll();
    const input = this.gamepadManager.getInput();

    // Merge virtual joystick input with gamepad/keyboard
    let stickX = input.leftStickX;
    let stickY = input.leftStickY;
    if (this.virtualJoystick && (this.virtualJoystick.axisX !== 0 || this.virtualJoystick.axisY !== 0)) {
      stickX = this.virtualJoystick.axisX;
      stickY = this.virtualJoystick.axisY;
    }

    // Move tactician based on input
    const dx = stickX * TACTICIAN_SPEED * (this.game.loop.delta / 1000);
    const dy = stickY * TACTICIAN_SPEED * (this.game.loop.delta / 1000);

    if (dx !== 0 || dy !== 0) {
      this.tactician.x = Phaser.Math.Clamp(this.tactician.x + dx, 16, this.worldWidth - 16);
      this.tactician.y = Phaser.Math.Clamp(this.tactician.y + dy, 16, this.worldHeight - 16);

      // Determine direction for walk animation
      if (Math.abs(dx) > Math.abs(dy)) {
        this.lastDirection = dx > 0 ? 'right' : 'left';
      } else {
        this.lastDirection = dy > 0 ? 'down' : 'up';
      }

      const walkKey = `tactician-walk-${this.lastDirection}`;
      if (this.anims.exists(walkKey) && this.tactician.anims.currentAnim?.key !== walkKey) {
        this.tactician.play(walkKey);
      }

      // Dust trail when walking
      const now = this.time.now;
      const positionDelta = Math.abs(this.tactician.x - this.lastSentX) + Math.abs(this.tactician.y - this.lastSentY);
      if (this.dustEmitter && positionDelta > 1) {
        this.dustEmitter.emitParticleAt(this.tactician.x, this.tactician.y + 12, 1);
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
      const idleKey = `tactician-idle-${this.lastDirection}`;
      if (this.anims.exists(idleKey) && this.tactician.anims.currentAnim?.key !== idleKey) {
        this.tactician.play(idleKey);
      }
    }

    // Update label position
    if (this.tacticianLabel) {
      this.tacticianLabel.setPosition(this.tactician.x, this.tactician.y - 24);
    }

    // Interpolate remote players toward their target positions
    this.remotePlayers.forEach((remote) => {
      const lerpFactor = 0.15;
      remote.sprite.x += (remote.targetX - remote.sprite.x) * lerpFactor;
      remote.sprite.y += (remote.targetY - remote.sprite.y) * lerpFactor;
      remote.label.setPosition(remote.sprite.x, remote.sprite.y - 24);

      // Play walk/idle animation based on movement
      const moving = Math.abs(remote.targetX - remote.sprite.x) > 0.5 ||
        Math.abs(remote.targetY - remote.sprite.y) > 0.5;
      if (moving) {
        const walkKey = `tactician-walk-${remote.direction}`;
        if (this.anims.exists(walkKey) && remote.sprite.anims.currentAnim?.key !== walkKey) {
          remote.sprite.play(walkKey);
        }
      } else {
        const idleKey = `tactician-idle-${remote.direction}`;
        if (this.anims.exists(idleKey) && remote.sprite.anims.currentAnim?.key !== idleKey) {
          remote.sprite.play(idleKey);
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
      const zoneBounds = layout ? { x: layout.x, y: layout.y, width: 192, height: 160 } : null;

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

      // Status particles (timer-gated)
      if (ENABLE_PARTICLES && this.textures.exists('particle-dot') && updateTime - agentSprite.lastParticleTime > 2000) {
        if (agentSprite.agentStatus === 'working') {
          agentSprite.lastParticleTime = updateTime;
          const sparkle = this.add.particles(agentSprite.sprite.x, agentSprite.sprite.y - 8, 'particle-dot', {
            speed: { min: 10, max: 30 },
            angle: { min: 230, max: 310 },
            lifespan: 600,
            alpha: { start: 0.6, end: 0 },
            tint: 0x06b6d4,
            scale: { start: 1, end: 0.3 },
            emitting: false,
          });
          sparkle.setDepth(6);
          sparkle.emitParticle(2);
          this.time.delayedCall(700, () => sparkle.destroy());
        } else if (agentSprite.agentStatus === 'error') {
          agentSprite.lastParticleTime = updateTime;
          const wisps = this.add.particles(agentSprite.sprite.x, agentSprite.sprite.y, 'particle-dot', {
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
    if (this.interactableManager) {
      this.interactableManager.destroy();
      this.interactableManager = null;
    }
    if (this.scriptBridge) {
      this.scriptBridge.destroy();
      this.scriptBridge = null;
    }
    if (this.virtualJoystick) {
      this.virtualJoystick.destroy();
      this.virtualJoystick = null;
    }
    if (this.touchButtons) {
      this.touchButtons.destroy();
      this.touchButtons = null;
    }
  }

  private createAnimations(): void {
    // Tactician animations — 4 directions × 3 walk frames
    // Spritesheet layout: frames 0-2 = down, 3-5 = left, 6-8 = up, 9-11 = right
    const directions = ['down', 'left', 'up', 'right'] as const;
    const hasTacticianSheet = this.textures.exists('tactician') &&
      this.textures.get('tactician').frameTotal > 1;

    if (hasTacticianSheet) {
      directions.forEach((dir, dirIndex) => {
        const startFrame = dirIndex * 3;

        this.anims.create({
          key: `tactician-walk-${dir}`,
          frames: this.anims.generateFrameNumbers('tactician', {
            start: startFrame,
            end: startFrame + 2,
          }),
          frameRate: 8,
          repeat: -1,
        });

        this.anims.create({
          key: `tactician-idle-${dir}`,
          frames: [{ key: 'tactician', frame: startFrame }],
          frameRate: 1,
          repeat: 0,
        });
      });
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
    // Tile the floor across the entire scene
    for (let x = 0; x < 1280; x += TILE_SIZE) {
      for (let y = 0; y < 720; y += TILE_SIZE) {
        const textureKey = this.textures.exists('floor-tile') ? 'floor-tile' : 'office-tileset';
        this.add.image(x + TILE_SIZE / 2, y + TILE_SIZE / 2, textureKey, 0).setAlpha(0.5);
      }
    }

    // Draw grid lines for visual structure
    const graphics = this.add.graphics();
    graphics.lineStyle(1, 0x334155, 0.3);
    for (let x = 0; x <= 1280; x += TILE_SIZE) {
      graphics.lineBetween(x, 0, x, 720);
    }
    for (let y = 0; y <= 720; y += TILE_SIZE) {
      graphics.lineBetween(0, y, 1280, y);
    }
  }

  private createDepartmentZones(): void {
    const zoneKeys: Record<string, string> = {
      engineering: 'zone-engineering',
      sales: 'zone-sales',
      support: 'zone-support',
      research: 'zone-research',
    };

    Object.entries(DEPARTMENT_LAYOUT).forEach(([slug, layout], index) => {
      const textureKey = zoneKeys[slug] ?? 'zone-engineering';
      const zone = this.add
        .image(layout.x, layout.y, textureKey)
        .setOrigin(0, 0)
        .setAlpha(0.2);
      this.departmentZones.push(zone);

      // Ambient breathing pulse on zone overlays
      this.tweens.add({
        targets: zone,
        alpha: { from: 0.2, to: 0.35 },
        duration: 3000 + index * 500,
        yoyo: true,
        repeat: -1,
        ease: 'Sine.easeInOut',
      });

      // Department label
      this.add
        .text(layout.x + 96, layout.y + 8, layout.label, {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: responsiveFontSize(10),
          color: '#94a3b8',
        })
        .setOrigin(0.5, 0);

      // Review station for each department (placed at bottom-right of zone)
      const stationX = layout.x + TILE_SIZE * 5;
      const stationY = layout.y + TILE_SIZE * 4;
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
    this.tactician = this.add.sprite(400, 300, 'tactician').setDepth(10).setAlpha(0).setScale(0.5);

    // Play initial idle animation if available
    if (this.anims.exists('tactician-idle-down')) {
      this.tactician.play('tactician-idle-down');
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

    // Indigo particle burst at spawn
    if (ENABLE_PARTICLES && this.textures.exists('particle-dot')) {
      const burst = this.add.particles(400, 300, 'particle-dot', {
        speed: { min: 20, max: 60 },
        angle: { min: 0, max: 360 },
        lifespan: 500,
        alpha: { start: 0.6, end: 0 },
        tint: 0x6366f1,
        scale: { start: 1.5, end: 0.5 },
        emitting: false,
      });
      burst.setDepth(11);
      burst.emitParticle(8);
      this.time.delayedCall(600, () => burst.destroy());
    }

    this.cameras.main.startFollow(this.tactician, true, 0.08, 0.08);
    this.cameras.main.setBounds(0, 0, this.worldWidth, this.worldHeight);

    // Label above tactician
    this.tacticianLabel = this.add
      .text(400, 276, 'YOU', {
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
    const bg = this.add.rectangle(0, 0, 420, 340, 0x0f172a, 0.95);

    const title = this.add
      .text(0, -140, 'KEYBOARD SHORTCUTS', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '10px',
        color: '#a5b4fc',
      })
      .setOrigin(0.5);

    const shortcuts = [
      'WASD / Arrows     Move',
      'ENTER / A (pad)   Approve',
      'ESC / B (pad)     Deny',
      'E / X (pad)       Inspect / Interact',
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
        // Update avatar texture if config changed
        if (player.avatarConfig) {
          try {
            const cfg = JSON.parse(player.avatarConfig) as AvatarConfig;
            const key = compositeAvatar(this, cfg);
            if (existing.sprite.texture.key !== key) {
              existing.sprite.setTexture(key);
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
        const sprite = this.add.sprite(player.x, player.y, remoteTexture).setDepth(9).setAlpha(0.85);
        if (this.anims.exists('tactician-idle-down')) {
          sprite.play('tactician-idle-down');
        }

        const label = this.add
          .text(player.x, player.y - 24, player.name, {
            fontFamily: '"Press Start 2P", monospace',
            fontSize: '7px',
            color: '#86efac',
          })
          .setOrigin(0.5)
          .setDepth(9);

        this.remotePlayers.set(player.sessionId, {
          sprite,
          label,
          targetX: player.x,
          targetY: player.y,
          direction: player.direction,
        });
      }
    }

    // Remove sprites for disconnected players
    this.remotePlayers.forEach((remote, sessionId) => {
      if (!currentSessionIds.has(sessionId)) {
        remote.sprite.destroy();
        remote.label.destroy();
        this.remotePlayers.delete(sessionId);
      }
    });
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
      return;
    }

    // Calculate position within department zone with some offset
    const agentIndex = dept.agents.indexOf(agent);
    const col = agentIndex % 3;
    const row = Math.floor(agentIndex / 3);
    const spriteX = layout.x + 48 + col * 48;
    const spriteY = layout.y + 48 + row * 48;

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
    const skills = (agent as any).skills as string[] | undefined;
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

  private getHaloStyle(status: string): { color: number; alpha: number } {
    switch (status) {
      case 'working': return { color: 0x06b6d4, alpha: 0.3 };
      case 'waiting_approval': return { color: 0xfbbf24, alpha: 0.4 };
      case 'error': return { color: 0xef4444, alpha: 0.3 };
      default: return { color: 0x64748b, alpha: 0.2 };
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
    this.tactician.setTexture(textureKey);
  }

  private showEmoteBubble(sessionId: string, emoteType: string): void {
    const frameIndex = EMOTE_FRAME_MAP[emoteType];
    if (frameIndex === undefined) return;

    // Find the sprite to attach the emote to
    let targetX: number;
    let targetY: number;

    if (sessionId === this.localSessionId) {
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
    // Find the nearest agent with a pending approval within proximity
    let nearestAgentId: string | null = null;
    let nearestDist = PROXIMITY_THRESHOLD;

    this.agentSprites.forEach((agentSprite) => {
      if (!agentSprite.hasPendingApproval) return;

      const dist = Phaser.Math.Distance.Between(
        this.tactician.x,
        this.tactician.y,
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
}
