'use client';

import { useRef, useEffect, useCallback } from 'react';
import type { OfficeState } from '@selva/shared-types';

/** Custom event bus for React <-> Phaser communication */
class GameEventBus extends EventTarget {
  /** Cached last value per event key — allows late subscribers to get the current state */
  private lastValue = new Map<string, unknown>();

  emit(event: string, detail?: unknown) {
    this.lastValue.set(event, detail);
    this.dispatchEvent(new CustomEvent(event, { detail }));
  }

  on(event: string, callback: (detail: unknown) => void) {
    const handler = (e: Event) => callback((e as CustomEvent).detail);
    this.addEventListener(event, handler);
    // Replay last cached value so late subscribers get the current state immediately
    const cached = this.lastValue.get(event);
    if (cached !== undefined) {
      callback(cached);
    }
    return () => this.removeEventListener(event, handler);
  }
}

export const gameEventBus = new GameEventBus();

interface PlayerEmoteEvent {
  sessionId: string;
  emoteType: string;
}

export interface CoWebsiteEvent {
  url: string;
  title: string;
}

export interface PopupEvent {
  title: string;
  content: string;
}

export interface DispatchEvent {
  title: string;
}

interface PhaserGameProps {
  onApprovalOpen?: (agentId: string) => void;
  officeState?: OfficeState | null;
  sessionId?: string | null;
  onPlayerMove?: (x: number, y: number) => void;
  onEmote?: (type: string) => void;
  onCoWebsite?: (event: CoWebsiteEvent) => void;
  onPopup?: (event: PopupEvent) => void;
  onDispatchOpen?: () => void;
  onBlueprintOpen?: () => void;
}

export default function PhaserGame({
  onApprovalOpen,
  officeState,
  sessionId,
  onPlayerMove,
  onEmote,
  onCoWebsite,
  onPopup,
  onDispatchOpen,
  onBlueprintOpen,
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

  // Listen for emote events from React (send to server)
  useEffect(() => {
    if (!onEmote) return;
    return gameEventBus.on('send-emote', (detail) => {
      const type = detail as string;
      onEmote(type);
    });
  }, [onEmote]);

  // Listen for cowebsite events from InteractableManager
  useEffect(() => {
    if (!onCoWebsite) return;
    return gameEventBus.on('open_cowebsite', (detail) => {
      onCoWebsite(detail as CoWebsiteEvent);
    });
  }, [onCoWebsite]);

  // Listen for popup events from InteractableManager
  useEffect(() => {
    if (!onPopup) return;
    return gameEventBus.on('show_popup', (detail) => {
      onPopup(detail as PopupEvent);
    });
  }, [onPopup]);

  // Listen for dispatch events from InteractableManager
  useEffect(() => {
    if (!onDispatchOpen) return;
    return gameEventBus.on('open_dispatch', () => {
      onDispatchOpen();
    });
  }, [onDispatchOpen]);

  // Listen for blueprint events from InteractableManager
  useEffect(() => {
    if (!onBlueprintOpen) return;
    return gameEventBus.on('open_blueprint', () => {
      onBlueprintOpen();
    });
  }, [onBlueprintOpen]);

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

    const container = containerRef.current;
    const config: Phaser.Types.Core.GameConfig = {
      type: Phaser.WEBGL,
      parent: container,
      width: container.clientWidth || window.innerWidth,
      height: container.clientHeight || window.innerHeight,
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
        mode: Phaser.Scale.RESIZE,
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
      aria-label="Selva Office game canvas"
      role="application"
    />
  );
}
