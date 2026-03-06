'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  OfficeState,
  Department,
  ReviewStation,
  TacticianPosition,
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
}

/**
 * React hook for Colyseus room connection.
 * Connects to the "office" room, listens for state changes,
 * and provides the current office state to React components.
 */
export function useColyseus(): ColyseusState {
  const [officeState, setOfficeState] = useState<OfficeState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const roomRef = useRef<unknown>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(async () => {
    try {
      // Dynamic import to avoid SSR issues
      const { Client } = await import('colyseus.js');
      const client = new Client(COLYSEUS_URL);
      const room = await client.joinOrCreate(ROOM_NAME);

      roomRef.current = room;
      setConnected(true);
      setError(null);
      reconnectAttempts.current = 0;

      // Listen for full state updates
      room.onStateChange((state: Record<string, unknown>) => {
        const departments = (state.departments ?? []) as Department[];
        const reviewStations = (state.reviewStations ?? []) as ReviewStation[];
        const tactician = (state.tactician ?? {
          x: 640,
          y: 360,
          direction: 'down',
        }) as TacticianPosition;

        let activeCount = 0;
        let pendingCount = 0;

        departments.forEach((dept: Department) => {
          dept.agents.forEach((agent) => {
            if (agent.status === 'working') activeCount++;
            if (agent.status === 'waiting_approval') pendingCount++;
          });
        });

        setOfficeState({
          departments,
          reviewStations,
          tactician,
          activeAgentCount: activeCount,
          pendingApprovalCount: pendingCount,
        });
      });

      room.onLeave((code: number) => {
        setConnected(false);
        roomRef.current = null;

        // Attempt reconnection on unexpected disconnects
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

      // Retry connection
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
      if (roomRef.current && typeof (roomRef.current as { leave: () => void }).leave === 'function') {
        (roomRef.current as { leave: () => void }).leave();
      }
      roomRef.current = null;
    };
  }, [connect]);

  return {
    room: roomRef.current,
    officeState,
    connected,
    error,
  };
}
