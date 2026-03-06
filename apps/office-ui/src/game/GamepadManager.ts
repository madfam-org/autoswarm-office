import type { GamepadInput } from '@autoswarm/shared-types';

const DEADZONE = 0.15;
const KEYBOARD_AXIS_VALUE = 1.0;

/**
 * HTML5 Gamepad API manager with keyboard fallback.
 *
 * Button mapping (Standard Gamepad Layout):
 *   A (index 0) = approve
 *   B (index 1) = deny
 *   X (index 2) = inspect
 *   Y (index 3) = menu
 *
 * Keyboard fallback:
 *   WASD       = left stick movement
 *   Arrow keys = right stick (camera)
 *   Enter      = A (approve)
 *   Escape     = B (deny)
 *   E          = X (inspect)
 *   Tab        = Y (menu)
 */
export class GamepadManager {
  private gamepad: Gamepad | null = null;
  private keysDown: Set<string> = new Set();
  private keysPressedThisFrame: Set<string> = new Set();
  private prevKeysDown: Set<string> = new Set();

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('keydown', this.onKeyDown);
      window.addEventListener('keyup', this.onKeyUp);
    }
  }

  destroy(): void {
    if (typeof window !== 'undefined') {
      window.removeEventListener('keydown', this.onKeyDown);
      window.removeEventListener('keyup', this.onKeyUp);
    }
  }

  /** Poll the gamepad state each frame. Call this in your scene's update(). */
  poll(): void {
    // Detect newly pressed keys this frame
    this.keysPressedThisFrame.clear();
    this.keysDown.forEach((key) => {
      if (!this.prevKeysDown.has(key)) {
        this.keysPressedThisFrame.add(key);
      }
    });
    this.prevKeysDown = new Set(this.keysDown);

    // Poll hardware gamepad
    if (typeof navigator !== 'undefined' && navigator.getGamepads) {
      const gamepads = navigator.getGamepads();
      this.gamepad = gamepads[0] ?? null;
    }
  }

  /** Returns the current input state, merging gamepad and keyboard. */
  getInput(): GamepadInput {
    const gp = this.gamepad;

    // Gamepad axes
    let leftStickX = gp ? this.applyDeadzone(gp.axes[0] ?? 0) : 0;
    let leftStickY = gp ? this.applyDeadzone(gp.axes[1] ?? 0) : 0;
    let rightStickX = gp ? this.applyDeadzone(gp.axes[2] ?? 0) : 0;
    let rightStickY = gp ? this.applyDeadzone(gp.axes[3] ?? 0) : 0;

    // Gamepad buttons (pressed this frame only for actions)
    let buttonA = gp ? gp.buttons[0]?.pressed ?? false : false;
    let buttonB = gp ? gp.buttons[1]?.pressed ?? false : false;
    let buttonX = gp ? gp.buttons[2]?.pressed ?? false : false;
    let buttonY = gp ? gp.buttons[3]?.pressed ?? false : false;

    // Keyboard fallback: WASD for left stick (held = continuous movement)
    if (this.keysDown.has('KeyW') || this.keysDown.has('ArrowUp')) {
      leftStickY = -KEYBOARD_AXIS_VALUE;
    }
    if (this.keysDown.has('KeyS') || this.keysDown.has('ArrowDown')) {
      leftStickY = KEYBOARD_AXIS_VALUE;
    }
    if (this.keysDown.has('KeyA') || this.keysDown.has('ArrowLeft')) {
      leftStickX = -KEYBOARD_AXIS_VALUE;
    }
    if (this.keysDown.has('KeyD') || this.keysDown.has('ArrowRight')) {
      leftStickX = KEYBOARD_AXIS_VALUE;
    }

    // Keyboard fallback: buttons (only fire on initial press)
    if (this.keysPressedThisFrame.has('Enter')) {
      buttonA = true;
    }
    if (this.keysPressedThisFrame.has('Escape')) {
      buttonB = true;
    }
    if (this.keysPressedThisFrame.has('KeyE')) {
      buttonX = true;
    }
    if (this.keysPressedThisFrame.has('Tab')) {
      buttonY = true;
    }

    return {
      leftStickX,
      leftStickY,
      rightStickX,
      rightStickY,
      buttonA,
      buttonB,
      buttonX,
      buttonY,
    };
  }

  private applyDeadzone(value: number): number {
    if (Math.abs(value) < DEADZONE) return 0;
    // Re-map the value so the range starts from 0 after the deadzone
    const sign = value > 0 ? 1 : -1;
    return sign * ((Math.abs(value) - DEADZONE) / (1 - DEADZONE));
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    // Prevent Tab from switching focus away from the game
    if (e.code === 'Tab') {
      e.preventDefault();
    }
    this.keysDown.add(e.code);
  };

  private onKeyUp = (e: KeyboardEvent): void => {
    this.keysDown.delete(e.code);
  };
}
