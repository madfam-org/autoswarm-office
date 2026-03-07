'use client';

import { useRef, useEffect, useCallback } from 'react';
import type { OfficeState } from '@autoswarm/shared-types';

/** Custom event bus for React <-> Phaser communication */
class GameEventBus extends EventTarget {
  emit(event: string, detail?: unknown) {
    this.dispatchEvent(new CustomEvent(event, { detail }));
  }

  on(event: string, callback: (detail: unknown) => void) {
    const handler = (e: Event) => callback((e as CustomEvent).detail);
    this.addEventListener(event, handler);
    return () => this.removeEventListener(event, handler);
  }
}

export const gameEventBus = new GameEventBus();

interface PhaserGameProps {
  onApprovalOpen?: (agentId: string) => void;
  officeState?: OfficeState | null;
  sessionId?: string | null;
  onPlayerMove?: (x: number, y: number) => void;
}

export default function PhaserGame({
  onApprovalOpen,
  officeState,
  sessionId,
  onPlayerMove,
}: PhaserGameProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<Phaser.Game | null>(null);

  // Listen for approval-open events from Phaser scenes
  useEffect(() => {
    if (!onApprovalOpen) return;
    return gameEventBus.on('approval-open', (detail) => {
      const agentId = detail as string;
      onApprovalOpen(agentId);
    });
  }, [onApprovalOpen]);

  // Listen for player-move events from Phaser scenes
  useEffect(() => {
    if (!onPlayerMove) return;
    return gameEventBus.on('player-move', (detail) => {
      const { x, y } = detail as { x: number; y: number };
      onPlayerMove(x, y);
    });
  }, [onPlayerMove]);

  // Forward session ID into Phaser via event bus
  useEffect(() => {
    if (sessionId) {
      gameEventBus.emit('session-id', sessionId);
    }
  }, [sessionId]);

  // Forward office state updates into Phaser via event bus
  useEffect(() => {
    if (officeState) {
      gameEventBus.emit('state-update', officeState);
    }
  }, [officeState]);

  const initGame = useCallback(async () => {
    if (gameRef.current || !containerRef.current) return;

    const Phaser = (await import('phaser')).default;
    const { BootScene } = await import('./scenes/BootScene');
    const { OfficeScene } = await import('./scenes/OfficeScene');

    const config: Phaser.Types.Core.GameConfig = {
      type: Phaser.WEBGL,
      parent: containerRef.current,
      width: 1280,
      height: 720,
      backgroundColor: '#0f172a',
      pixelArt: true,
      physics: {
        default: 'arcade',
        arcade: {
          gravity: { x: 0, y: 0 },
          debug: false,
        },
      },
      scene: [BootScene, OfficeScene],
      scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
      },
      input: {
        gamepad: true,
      },
    };

    gameRef.current = new Phaser.Game(config);
  }, []);

  useEffect(() => {
    initGame();

    return () => {
      if (gameRef.current) {
        gameRef.current.destroy(true);
        gameRef.current = null;
      }
    };
  }, [initGame]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 z-0"
      aria-label="AutoSwarm Office game canvas"
      role="application"
    />
  );
}
