import Phaser from 'phaser';

export interface TouchButtonEvents {
  onApprove: () => void;
  onDeny: () => void;
  onInspect: () => void;
  onEmote: () => void;
}

/**
 * Touch action buttons for mobile, positioned at the bottom-right.
 * Shows 4 circular buttons: Approve (green), Deny (red), Inspect (cyan), Emote (yellow).
 */
export class TouchActionButtons {
  private scene: Phaser.Scene;
  private buttons: Phaser.GameObjects.Container;

  constructor(scene: Phaser.Scene, events: TouchButtonEvents) {
    this.scene = scene;

    const baseX = scene.scale.width - 80;
    const baseY = scene.scale.height - 80;

    this.buttons = scene.add.container(baseX, baseY)
      .setScrollFactor(0)
      .setDepth(200);

    // Approve (top) — green
    this.createButton(0, -36, 0x22c55e, 'A', () => events.onApprove());
    // Deny (left) — red
    this.createButton(-36, 0, 0xef4444, 'D', () => events.onDeny());
    // Inspect (right) — cyan
    this.createButton(36, 0, 0x06b6d4, 'E', () => events.onInspect());
    // Emote (bottom) — yellow
    this.createButton(0, 36, 0xfbbf24, 'R', () => events.onEmote());
  }

  setVisible(visible: boolean): void {
    this.buttons.setVisible(visible);
  }

  destroy(): void {
    this.buttons.destroy();
  }

  private createButton(
    x: number,
    y: number,
    color: number,
    label: string,
    callback: () => void,
  ): void {
    const circle = this.scene.add.circle(x, y, 18, color, 0.6)
      .setInteractive()
      .on('pointerdown', callback);

    const text = this.scene.add.text(x, y, label, {
      fontFamily: '"Press Start 2P", monospace',
      fontSize: '8px',
      color: '#ffffff',
    }).setOrigin(0.5);

    this.buttons.add([circle, text]);
  }
}
