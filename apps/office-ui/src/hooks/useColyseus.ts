'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  OfficeState,
  Department,
  ReviewStation,
  Player,
  ChatMessage,
  Agent,
} from '@selva/shared-types';
import { MAX_RECONNECT_DELAY_MS } from '@/lib/constants';

const COLYSEUS_URL = process.env.NEXT_PUBLIC_COLYSEUS_URL ?? 'ws://localhost:4303';
const ROOM_NAME = 'office';

export interface PlayerEmoteEvent {
  sessionId: string;
  emoteType: string;
}

export interface ProximityUpdate {
  nearbySessionIds: string[];
  /** Transport mode: 'p2p' (simple-peer) or 'sfu' (LiveKit). Defaults to 'p2p'. */
  mode?: 'p2p' | 'sfu';
}

export interface WebRTCSignal {
  fromSessionId: string;
  signal: unknown;
}

export interface SpotlightActiveEvent {
  sessionId: string;
  name?: string;
  active: boolean;
}

export interface LiveKitCredentialsEvent {
  url: string;
  token: string;
}

interface ColyseusOptions {
  playerName?: string;
  onPlayerEmote?: (event: PlayerEmoteEvent) => void;
  onProximityUpdate?: (update: ProximityUpdate) => void;
  onWebRTCSignal?: (signal: WebRTCSignal) => void;
  onSpotlightActive?: (event: SpotlightActiveEvent) => void;
  onLiveKitCredentials?: (creds: LiveKitCredentialsEvent) => void;
}

interface ColyseusState {
  room: unknown | null;
  officeState: OfficeState | null;
  connected: boolean;
  error: string | null;
  sessionId: string | null;
  sendMove: (x: number, y: number) => void;
  sendChat: (content: string) => void;
  sendEmote: (type: string) => void;
  sendAvatarConfig: (config: string) => void;
  sendStatus: (status: string) => void;
  sendSignal: (targetSessionId: string, signal: unknown) => void;
  sendCompanion: (type: string) => void;
  sendMusicStatus: (status: string) => void;
  sendMegaphoneStart: () => void;
  sendMegaphoneStop: () => void;
  sendSpotlightStart: () => void;
  sendSpotlightStop: () => void;
  sendLockBubble: () => void;
  sendUnlockBubble: () => void;
}

interface RoomLike {
  sessionId: string;
  send: (type: string, data: unknown) => void;
  leave: () => void;
  onStateChange: (cb: (state: Record<string, unknown>) => void) => void;
  onMessage: (type: string, cb: (message: unknown) => void) => void;
  onLeave: (cb: (code: number) => void) => void;
  onError: (cb: (code: number, message?: string) => void) => void;
}

function parseMapSchema<T>(map: unknown): T[] {
  if (!map) return [];
  if (typeof (map as Iterable<unknown>)[Symbol.iterator] === 'function') {
    // Colyseus MapSchema is iterable as [key, value] pairs
    const result: T[] = [];
    for (const [, value] of map as Iterable<[string, T]>) {
      result.push(value);
    }
    return result;
  }
  if (typeof map === 'object' && map !== null && 'forEach' in map) {
    const result: T[] = [];
    (map as { forEach: (cb: (v: T) => void) => void }).forEach((v: T) => result.push(v));
    return result;
  }
  return [];
}

function parseArraySchema<T>(arr: unknown): T[] {
  if (!arr) return [];
  if (Array.isArray(arr)) return arr;
  if (typeof (arr as Iterable<unknown>)[Symbol.iterator] === 'function') {
    return [...(arr as Iterable<T>)];
  }
  return [];
}

export function useColyseus(options?: string | ColyseusOptions): ColyseusState {
  // Support both `useColyseus('Name')` and `useColyseus({ playerName, onPlayerEmote })`
  const opts: ColyseusOptions = typeof options === 'string'
    ? { playerName: options }
    : options ?? {};

  const [officeState, setOfficeState] = useState<OfficeState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const roomRef = useRef<RoomLike | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const playerNameRef = useRef(opts.playerName);
  playerNameRef.current = opts.playerName;
  const onPlayerEmoteRef = useRef(opts.onPlayerEmote);
  onPlayerEmoteRef.current = opts.onPlayerEmote;
  const onProximityUpdateRef = useRef(opts.onProximityUpdate);
  onProximityUpdateRef.current = opts.onProximityUpdate;
  const onWebRTCSignalRef = useRef(opts.onWebRTCSignal);
  onWebRTCSignalRef.current = opts.onWebRTCSignal;
  const onSpotlightActiveRef = useRef(opts.onSpotlightActive);
  onSpotlightActiveRef.current = opts.onSpotlightActive;
  const onLiveKitCredentialsRef = useRef(opts.onLiveKitCredentials);
  onLiveKitCredentialsRef.current = opts.onLiveKitCredentials;

  const sendMove = useCallback((x: number, y: number) => {
    roomRef.current?.send('move', { x, y });
  }, []);

  const sendChat = useCallback((content: string) => {
    roomRef.current?.send('chat', { content });
  }, []);

  const sendEmote = useCallback((type: string) => {
    roomRef.current?.send('emote', { type });
  }, []);

  const sendAvatarConfig = useCallback((config: string) => {
    roomRef.current?.send('avatar', { config });
  }, []);

  const sendStatus = useCallback((status: string) => {
    roomRef.current?.send('status', { status });
  }, []);

  const sendSignal = useCallback((targetSessionId: string, signal: unknown) => {
    roomRef.current?.send('webrtc_signal', { targetSessionId, signal });
  }, []);

  const sendCompanion = useCallback((type: string) => {
    roomRef.current?.send('companion', { type });
  }, []);

  const sendMusicStatus = useCallback((status: string) => {
    roomRef.current?.send('music_status', { status });
  }, []);

  const sendMegaphoneStart = useCallback(() => {
    roomRef.current?.send('megaphone_start', {});
  }, []);

  const sendMegaphoneStop = useCallback(() => {
    roomRef.current?.send('megaphone_stop', {});
  }, []);

  const sendSpotlightStart = useCallback(() => {
    roomRef.current?.send('spotlight_start', {});
  }, []);

  const sendSpotlightStop = useCallback(() => {
    roomRef.current?.send('spotlight_stop', {});
  }, []);

  const sendLockBubble = useCallback(() => {
    roomRef.current?.send('lock_bubble', {});
  }, []);

  const sendUnlockBubble = useCallback(() => {
    roomRef.current?.send('unlock_bubble', {});
  }, []);

  const connect = useCallback(async () => {
    try {
      const { Client } = await import('colyseus.js');
      const client = new Client(COLYSEUS_URL);
      const room = await client.joinOrCreate(ROOM_NAME, {
        name: playerNameRef.current ?? 'Player',
      });

      roomRef.current = room as unknown as RoomLike;
      setConnected(true);
      setError(null);
      setSessionId(room.sessionId);
      reconnectAttempts.current = 0;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      room.onStateChange((rawState: any) => {
        const state = rawState as Record<string, unknown>;

        const departments = parseMapSchema<Department>(state.departments);
        const reviewStations = (state.reviewStations ?? []) as ReviewStation[];
        const players = parseMapSchema<Player>(state.players);
        const chatMessages = parseArraySchema<ChatMessage>(state.chatMessages);

        let activeCount = 0;
        let pendingCount = 0;

        departments.forEach((dept: Department) => {
          if (dept.agents) {
            const agents = parseArraySchema<Agent>(dept.agents);
            agents.forEach((agent) => {
              if (agent.status === 'working') activeCount++;
              if (agent.status === 'waiting_approval') pendingCount++;
            });
          }
        });

        setOfficeState({
          departments,
          reviewStations,
          players,
          localSessionId: room.sessionId,
          activeAgentCount: activeCount,
          pendingApprovalCount: pendingCount,
          chatMessages,
        });
      });

      // Listen for ephemeral emote broadcasts and forward via callback
      (room as unknown as RoomLike).onMessage('player_emote', (message: unknown) => {
        const event = message as PlayerEmoteEvent;
        onPlayerEmoteRef.current?.(event);
      });

      // Listen for proximity updates (for WebRTC peer management)
      (room as unknown as RoomLike).onMessage('proximity_players', (message: unknown) => {
        onProximityUpdateRef.current?.(message as ProximityUpdate);
      });

      // Listen for WebRTC signaling messages
      (room as unknown as RoomLike).onMessage('webrtc_signal', (message: unknown) => {
        onWebRTCSignalRef.current?.(message as WebRTCSignal);
      });

      // Listen for spotlight presentation broadcasts
      (room as unknown as RoomLike).onMessage('spotlight_active', (message: unknown) => {
        onSpotlightActiveRef.current?.(message as SpotlightActiveEvent);
      });

      // Listen for LiveKit SFU credentials (sent on join when LiveKit is configured)
      (room as unknown as RoomLike).onMessage('livekit_credentials', (message: unknown) => {
        onLiveKitCredentialsRef.current?.(message as LiveKitCredentialsEvent);
      });

      room.onLeave((code: number) => {
        setConnected(false);
        roomRef.current = null;
        setSessionId(null);

        if (code !== 1000) {
          reconnectAttempts.current++;
          const delay = Math.min(MAX_RECONNECT_DELAY_MS, 1000 * Math.pow(2, reconnectAttempts.current)) + Math.random() * 1000;
          reconnectTimer.current = setTimeout(connect, delay);
        }
      });

      room.onError((code: number, message?: string) => {
        setError(`Colyseus error ${code}: ${message ?? 'Unknown error'}`);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Connection failed';
      setError(message);
      setConnected(false);

      reconnectAttempts.current++;
      const delay = Math.min(MAX_RECONNECT_DELAY_MS, 1000 * Math.pow(2, reconnectAttempts.current)) + Math.random() * 1000;
      reconnectTimer.current = setTimeout(connect, delay);
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      roomRef.current?.leave();
      roomRef.current = null;
    };
  }, [connect]);

  return {
    room: roomRef.current,
    officeState,
    connected,
    error,
    sessionId,
    sendMove,
    sendChat,
    sendEmote,
    sendAvatarConfig,
    sendStatus,
    sendSignal,
    sendCompanion,
    sendMusicStatus,
    sendMegaphoneStart,
    sendMegaphoneStop,
    sendSpotlightStart,
    sendSpotlightStop,
    sendLockBubble,
    sendUnlockBubble,
  };
}
