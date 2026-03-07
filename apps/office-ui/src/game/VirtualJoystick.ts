import Phaser from 'phaser';

const BASE_RADIUS = 40;
const THUMB_RADIUS = 16;
const DEADZONE = 0.2;

/**
 * Custom virtual joystick for mobile touch input.
 * Renders at the bottom-left of the screen, only visible on touch devices.
 */
export class VirtualJoystick {
  private scene: Phaser.Scene;
  private base: Phaser.GameObjects.Arc;
  private thumb: Phaser.GameObjects.Arc;
  private active: boolean = false;
  private startX: number = 0;
  private startY: number = 0;
  private _axisX: number = 0;
  private _axisY: number = 0;
  private pointerId: number = -1;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;

    const baseX = 80;
    const baseY = scene.scale.height - 80;

    this.base = scene.add.circle(baseX, baseY, BASE_RADIUS, 0x64748b, 0.3)
      .setScrollFactor(0)
      .setDepth(200);

    this.thumb = scene.add.circle(baseX, baseY, THUMB_RADIUS, 0xa5b4fc, 0.6)
      .setScrollFactor(0)
      .setDepth(201);

    scene.input.on('pointerdown', this.onPointerDown, this);
    scene.input.on('pointermove', this.onPointerMove, this);
    scene.input.on('pointerup', this.onPointerUp, this);
  }

  get axisX(): number {
    return this._axisX;
  }

  get axisY(): number {
    return this._axisY;
  }

  setVisible(visible: boolean): void {
    this.base.setVisible(visible);
    this.thumb.setVisible(visible);
  }

  destroy(): void {
    this.scene.input.off('pointerdown', this.onPointerDown, this);
    this.scene.input.off('pointermove', this.onPointerMove, this);
    this.scene.input.off('pointerup', this.onPointerUp, this);
    this.base.destroy();
    this.thumb.destroy();
  }

  private onPointerDown = (pointer: Phaser.Input.Pointer): void => {
    // Only respond to left-side touches (joystick zone)
    if (pointer.x > this.scene.scale.width / 2) return;
    if (this.active) return;

    this.active = true;
    this.pointerId = pointer.id;
    this.startX = this.base.x;
    this.startY = this.base.y;
    this.updateThumb(pointer.x, pointer.y);
  };

  private onPointerMove = (pointer: Phaser.Input.Pointer): void => {
    if (!this.active || pointer.id !== this.pointerId) return;
    this.updateThumb(pointer.x, pointer.y);
  };

  private onPointerUp = (pointer: Phaser.Input.Pointer): void => {
    if (!this.active || pointer.id !== this.pointerId) return;
    this.active = false;
    this.pointerId = -1;
    this._axisX = 0;
    this._axisY = 0;
    this.thumb.setPosition(this.base.x, this.base.y);
  };

  private updateThumb(pointerX: number, pointerY: number): void {
    const dx = pointerX - this.startX;
    const dy = pointerY - this.startY;
    const dist = Math.sqrt(dx * dx + dy * dy);

    let clampedX = dx;
    let clampedY = dy;

    if (dist > BASE_RADIUS) {
      const scale = BASE_RADIUS / dist;
      clampedX = dx * scale;
      clampedY = dy * scale;
    }

    this.thumb.setPosition(this.startX + clampedX, this.startY + clampedY);

    // Normalize to -1..1 range with deadzone
    const normalizedDist = Math.min(dist / BASE_RADIUS, 1);
    if (normalizedDist < DEADZONE) {
      this._axisX = 0;
      this._axisY = 0;
    } else {
      const angle = Math.atan2(dy, dx);
      const remapped = (normalizedDist - DEADZONE) / (1 - DEADZONE);
      this._axisX = Math.cos(angle) * remapped;
      this._axisY = Math.sin(angle) * remapped;
    }
  }
}
