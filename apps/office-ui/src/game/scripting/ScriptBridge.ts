import Phaser from 'phaser';
import { gameEventBus } from '../PhaserGame';
import { buildScriptAPISource } from './ScriptAPI';
import type { ScriptCommand } from './ScriptAPI';
import { logger } from '@/lib/logger';

const ALLOWED_COMMANDS = new Set([
  'chat.sendMessage',
  'camera.moveTo',
  'player.moveTo',
  'ui.openPopup',
  'ui.openCoWebsite',
  'script.error',
]);

/**
 * Manages hidden iframe elements for map scripts.
 * Scripts communicate with the game via postMessage bridge.
 */
export class ScriptBridge {
  private scene: Phaser.Scene;
  private iframes: HTMLIFrameElement[] = [];
  private messageHandler: (event: MessageEvent) => void;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    this.messageHandler = this.handleMessage.bind(this);
    window.addEventListener('message', this.messageHandler);
  }

  /**
   * Load and execute a script in a sandboxed iframe.
   */
  loadScript(url: string): void {
    const apiSource = buildScriptAPISource();

    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.setAttribute('sandbox', 'allow-scripts');
    iframe.srcdoc = `<!DOCTYPE html>
<html><head><script>${apiSource}</script></head>
<body><script src="${this.sanitizeUrl(url)}"></script></body></html>`;

    document.body.appendChild(iframe);
    this.iframes.push(iframe);
  }

  /**
   * Forward area enter/leave events to script iframes.
   */
  notifyAreaEvent(areaName: string, eventType: 'enter' | 'leave'): void {
    const type = eventType === 'enter' ? 'area.onEnter' : 'area.onLeave';
    for (const iframe of this.iframes) {
      iframe.contentWindow?.postMessage(
        { __selva_event: true, type, areaName },
        '*',
      );
    }
  }

  destroy(): void {
    window.removeEventListener('message', this.messageHandler);
    for (const iframe of this.iframes) {
      iframe.remove();
    }
    this.iframes = [];
  }

  private handleMessage(event: MessageEvent): void {
    const data = event.data as Record<string, unknown>;
    if (!data || data.__selva !== true) return;

    const type = data.type as string | undefined;
    if (!type || !ALLOWED_COMMANDS.has(type)) return;

    if (type === 'script.error') {
      // Errors are forwarded by the iframe API stub; surface them only in
      // dev so end users don't see noisy console output for buggy maps.
      logger.warn('[AS Script]', data.message);
      return;
    }

    const cmd = data as unknown as ScriptCommand & { __selva: boolean };
    switch (cmd.type) {
      case 'chat.sendMessage':
        gameEventBus.emit('script-chat', cmd.content);
        break;
      case 'camera.moveTo':
        this.scene.cameras.main.pan(cmd.x, cmd.y, 500, 'Sine.easeInOut');
        break;
      case 'player.moveTo':
        gameEventBus.emit('script-player-move', { x: cmd.x, y: cmd.y });
        break;
      case 'ui.openPopup':
        gameEventBus.emit('show_popup', { title: cmd.title, content: cmd.content });
        break;
      case 'ui.openCoWebsite':
        gameEventBus.emit('open_cowebsite', { url: cmd.url, title: cmd.title ?? '' });
        break;
    }
  }

  private sanitizeUrl(url: string): string {
    // Only allow http(s) URLs and relative paths
    if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('/')) {
      return url;
    }
    return '';
  }
}
