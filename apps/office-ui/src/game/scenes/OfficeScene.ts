import Phaser from 'phaser';
import { GamepadManager } from '../GamepadManager';
import { gameEventBus } from '../PhaserGame';
import type {
  OfficeState,
  Department,
  ReviewStation,
  Agent,
} from '@autoswarm/shared-types';

const TILE_SIZE = 32;
const TACTICIAN_SPEED = 200;
const PROXIMITY_THRESHOLD = 64;

interface AgentSprite {
  sprite: Phaser.GameObjects.Sprite;
  alertIcon: Phaser.GameObjects.Image;
  agentId: string;
  hasPendingApproval: boolean;
}

/** Department zone layout positions on the office grid */
const DEPARTMENT_LAYOUT: Record<string, { x: number; y: number; label: string }> = {
  engineering: { x: 96, y: 80, label: 'ENGINEERING' },
  sales: { x: 480, y: 80, label: 'SALES' },
  support: { x: 96, y: 400, label: 'SUPPORT' },
  research: { x: 480, y: 400, label: 'RESEARCH' },
};

const AGENT_ROLES = ['planner', 'coder', 'reviewer', 'researcher', 'crm', 'support'] as const;

export class OfficeScene extends Phaser.Scene {
  private gamepadManager!: GamepadManager;
  private tactician!: Phaser.GameObjects.Sprite;
  private agentSprites: Map<string, AgentSprite> = new Map();
  private departmentZones: Phaser.GameObjects.Image[] = [];
  private reviewStations: Map<string, Phaser.GameObjects.Image> = new Map();
  private officeState: OfficeState | null = null;
  private stateCleanup: (() => void) | null = null;
  private helpOverlay!: Phaser.GameObjects.Container;
  private lastDirection: string = 'down';

  constructor() {
    super({ key: 'OfficeScene' });
  }

  create(): void {
    this.createAnimations();

    this.gamepadManager = new GamepadManager();

    this.createFloor();
    this.createDepartmentZones();
    this.createTactician();

    // Listen for state updates from React
    this.stateCleanup = gameEventBus.on('state-update', (detail) => {
      this.onStateUpdate(detail as OfficeState);
    });

    // Add keyboard instructions text
    this.add
      .text(640, 700, 'WASD: Move | ENTER: Approve | ESC: Deny | E: Inspect | TAB: Menu | ?: Help', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#64748b',
      })
      .setOrigin(0.5)
      .setScrollFactor(0);

    this.createHelpOverlay();

    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      if (event.key === '?') {
        this.helpOverlay.setVisible(!this.helpOverlay.visible);
      }
    });
  }

  update(): void {
    this.gamepadManager.poll();
    const input = this.gamepadManager.getInput();

    // Move tactician based on input
    const dx = input.leftStickX * TACTICIAN_SPEED * (this.game.loop.delta / 1000);
    const dy = input.leftStickY * TACTICIAN_SPEED * (this.game.loop.delta / 1000);

    if (dx !== 0 || dy !== 0) {
      this.tactician.x = Phaser.Math.Clamp(this.tactician.x + dx, 16, 1264);
      this.tactician.y = Phaser.Math.Clamp(this.tactician.y + dy, 16, 704);

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
    } else {
      // Idle: show single frame for current direction
      const idleKey = `tactician-idle-${this.lastDirection}`;
      if (this.anims.exists(idleKey) && this.tactician.anims.currentAnim?.key !== idleKey) {
        this.tactician.play(idleKey);
      }
    }

    // Check button presses for proximity interactions
    if (input.buttonA) {
      this.handleProximityInteraction('approve');
    }
    if (input.buttonX) {
      this.handleProximityInteraction('inspect');
    }

    // Animate alert icons
    this.agentSprites.forEach((agentSprite) => {
      if (agentSprite.hasPendingApproval) {
        agentSprite.alertIcon.setVisible(true);
        agentSprite.alertIcon.setPosition(
          agentSprite.sprite.x + 12,
          agentSprite.sprite.y - 20,
        );
        // Bob animation
        agentSprite.alertIcon.y +=
          Math.sin(this.time.now / 300) * 2;
      } else {
        agentSprite.alertIcon.setVisible(false);
      }
    });
  }

  destroy(): void {
    if (this.stateCleanup) {
      this.stateCleanup();
      this.stateCleanup = null;
    }
    super.destroy();
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

    Object.entries(DEPARTMENT_LAYOUT).forEach(([slug, layout]) => {
      const textureKey = zoneKeys[slug] ?? 'zone-engineering';
      const zone = this.add
        .image(layout.x, layout.y, textureKey)
        .setOrigin(0, 0)
        .setAlpha(0.3);
      this.departmentZones.push(zone);

      // Department label
      this.add
        .text(layout.x + 96, layout.y + 8, layout.label, {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: '10px',
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
    this.tactician = this.add.sprite(640, 360, 'tactician').setDepth(10);

    // Play initial idle animation if available
    if (this.anims.exists('tactician-idle-down')) {
      this.tactician.play('tactician-idle-down');
    }

    this.cameras.main.startFollow(this.tactician, true, 0.08, 0.08);
    this.cameras.main.setBounds(0, 0, 1280, 720);

    // Label above tactician
    const label = this.add
      .text(640, 340, 'YOU', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#a5b4fc',
      })
      .setOrigin(0.5)
      .setDepth(10);

    // Keep label following the tactician
    this.events.on('update', () => {
      label.setPosition(this.tactician.x, this.tactician.y - 24);
    });
  }

  private createHelpOverlay(): void {
    this.helpOverlay = this.add.container(640, 360).setDepth(100).setVisible(false);

    const bg = this.add.rectangle(0, 0, 400, 300, 0x000000, 0.85);

    const title = this.add
      .text(0, -120, 'KEYBOARD SHORTCUTS', {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '10px',
        color: '#a5b4fc',
      })
      .setOrigin(0.5);

    const shortcuts = [
      'WASD / Arrows  -  Move',
      'ENTER / A      -  Approve',
      'ESC / B        -  Deny',
      'E / X          -  Inspect',
      'TAB            -  Menu',
      '?              -  Toggle Help',
    ];

    const lines = shortcuts.map((text, i) =>
      this.add.text(-160, -70 + i * 30, text, {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '8px',
        color: '#cbd5e1',
      }),
    );

    this.helpOverlay.add([bg, title, ...lines]);

    // Make it scroll-fixed so it stays centered on screen
    this.helpOverlay.setScrollFactor(0);
  }

  private onStateUpdate(state: OfficeState): void {
    this.officeState = state;

    // Reconcile agent sprites with current state
    const currentAgentIds = new Set<string>();

    state.departments.forEach((dept: Department) => {
      dept.agents.forEach((agent: Agent) => {
        currentAgentIds.add(agent.id);
        this.updateOrCreateAgentSprite(agent, dept);
      });
    });

    // Remove sprites for agents no longer in state
    this.agentSprites.forEach((agentSprite, agentId) => {
      if (!currentAgentIds.has(agentId)) {
        agentSprite.sprite.destroy();
        agentSprite.alertIcon.destroy();
        this.agentSprites.delete(agentId);
      }
    });

    // Update review station pending counts
    state.reviewStations.forEach((station: ReviewStation) => {
      const stationSprite = this.reviewStations.get(station.departmentId);
      if (stationSprite) {
        stationSprite.setAlpha(station.pendingApprovals > 0 ? 1 : 0.5);
      }
    });
  }

  private updateOrCreateAgentSprite(agent: Agent, dept: Department): void {
    const textureKey = `agent-${agent.role}`;
    const layout = DEPARTMENT_LAYOUT[dept.slug];
    if (!layout) return;

    const existing = this.agentSprites.get(agent.id);
    const hasPending = agent.status === 'waiting_approval';

    if (existing) {
      // Update existing sprite state
      existing.hasPendingApproval = hasPending;

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

    // Agent name label
    this.add
      .text(spriteX, spriteY + 20, agent.name.substring(0, 8), {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: '6px',
        color: '#cbd5e1',
      })
      .setOrigin(0.5, 0)
      .setDepth(5);

    this.agentSprites.set(agent.id, {
      sprite,
      alertIcon,
      agentId: agent.id,
      hasPendingApproval: hasPending,
    });
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

    if (nearestAgentId && action === 'approve') {
      gameEventBus.emit('approval-open', nearestAgentId);
    }
  }
}
