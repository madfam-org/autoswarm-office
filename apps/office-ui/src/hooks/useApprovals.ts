'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type { ApprovalRequest, ApprovalResponse } from '@autoswarm/shared-types';

const WS_URL =
  process.env.NEXT_PUBLIC_APPROVALS_WS_URL ?? 'ws://localhost:4300/api/v1/approvals/ws';
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:4300';
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 15;

interface ApprovalsState {
  pendingApprovals: ApprovalRequest[];
  approve: (requestId: string, feedback?: string) => void;
  deny: (requestId: string, feedback?: string) => void;
  connected: boolean;
}

interface WSMessage {
  type: string;
  payload: unknown;
}

/**
 * React hook for the approval queue.
 * Connects to the nexus-api WebSocket, listens for approval_request events,
 * and provides approve/deny actions.
 */
export function useApprovals(): ApprovalsState {
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const message: WSMessage = JSON.parse(event.data as string);

          switch (message.type) {
            case 'approval_request': {
              const request = message.payload as ApprovalRequest;
              setPendingApprovals((prev) => {
                // Avoid duplicates
                if (prev.some((a) => a.id === request.id)) return prev;
                return [...prev, request];
              });
              break;
            }

            case 'approval_resolved': {
              const response = message.payload as ApprovalResponse;
              setPendingApprovals((prev) =>
                prev.filter((a) => a.id !== response.requestId),
              );
              break;
            }

            case 'approval_batch': {
              const requests = message.payload as ApprovalRequest[];
              setPendingApprovals(requests);
              break;
            }

            case 'ping': {
              // Respond to keep-alive
              ws.send(JSON.stringify({ type: 'pong' }));
              break;
            }
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = (event: CloseEvent) => {
        setConnected(false);
        wsRef.current = null;

        if (event.code !== 1000 && reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempts.current++;
          reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => {
        // onclose will fire after onerror, so reconnection is handled there
        setConnected(false);
      };
    } catch {
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
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendDecision = useCallback(
    async (requestId: string, decision: 'approve' | 'deny', feedback?: string) => {
      const url = `${API_BASE_URL}/api/v1/approvals/${requestId}/${decision}`;
      const body: Record<string, unknown> = {};
      if (feedback !== undefined) {
        body.feedback = feedback;
      }

      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          credentials: 'include',
        });

        if (res.ok) {
          // Optimistically remove from pending -- the WS will also broadcast the
          // resolution, but removing immediately gives a snappy UI.
          setPendingApprovals((prev) => prev.filter((a) => a.id !== requestId));
        }
      } catch {
        // Network errors are silently ignored; the approval stays in the queue
        // and the user can retry.
      }
    },
    [],
  );

  const approve = useCallback(
    (requestId: string, feedback?: string) => {
      void sendDecision(requestId, 'approve', feedback);
    },
    [sendDecision],
  );

  const deny = useCallback(
    (requestId: string, feedback?: string) => {
      void sendDecision(requestId, 'deny', feedback);
    },
    [sendDecision],
  );

  return {
    pendingApprovals,
    approve,
    deny,
    connected,
  };
}
