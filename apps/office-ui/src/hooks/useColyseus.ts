'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  OfficeState,
  Department,
  ReviewStation,
  Player,
  ChatMessage,
} from '@autoswarm/shared-types';

const COLYSEUS_URL = process.env.NEXT_PUBLIC_COLYSEUS_URL ?? 'ws://localhost:4303';
const ROOM_NAME = 'office';
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

interface ColyseusState {
  room: unknown | null;
  officeState: OfficeState | null;
  connected: boolean;
  error: string | null;
  sessionId: string | null;
  sendMove: (x: number, y: number) => void;
  sendChat: (content: string) => void;
}

interface RoomLike {
  sessionId: string;
  send: (type: string, data: unknown) => void;
  leave: () => void;
  onStateChange: (cb: (state: Record<string, unknown>) => void) => void;
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

export function useColyseus(playerName?: string): ColyseusState {
  const [officeState, setOfficeState] = useState<OfficeState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const roomRef = useRef<RoomLike | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const playerNameRef = useRef(playerName);
  playerNameRef.current = playerName;

  const sendMove = useCallback((x: number, y: number) => {
    roomRef.current?.send('move', { x, y });
  }, []);

  const sendChat = useCallback((content: string) => {
    roomRef.current?.send('chat', { content });
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
            const agents = parseArraySchema(dept.agents);
            agents.forEach((agent: any) => {
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

      room.onLeave((code: number) => {
        setConnected(false);
        roomRef.current = null;
        setSessionId(null);

        if (code !== 1000 && reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempts.current++;
          reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      });

      room.onError((code: number, message?: string) => {
        setError(`Colyseus error ${code}: ${message ?? 'Unknown error'}`);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Connection failed';
      setError(message);
      setConnected(false);

      if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts.current++;
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
      }
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
  };
}
