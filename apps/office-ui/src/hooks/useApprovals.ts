'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  ActionCategory,
  ApprovalRequest,
  WireApprovalAction,
  WireApprovalRequest,
} from '@selva/shared-types';
import { apiFetch, getSessionToken, isDemo } from '@/lib/api';
import { MAX_RECONNECT_DELAY_MS } from '@/lib/constants';

// ---------------------------------------------------------------------------
// Wire → domain conversion
// ---------------------------------------------------------------------------
//
// The WS messages `approval_request` and `approval_resolved` carry the
// snake_case `nexus_api__routers__approvals__ApprovalRequestResponse`
// schema (see `apps/nexus-api/nexus_api/routers/approvals.py:158` —
// payload is `_approval_to_response(...).model_dump(mode="json")`).
// Components (ApprovalPanel, SimplifiedView) consume the camelCase domain
// `ApprovalRequest`. Convert at the boundary so the cast actually
// matches the shape on the wire — the previous `as ApprovalRequest` cast
// silently produced an object whose camelCase getters were all undefined,
// which the components rendered as blank cells.
//
const URGENCY_VALUES = ['low', 'medium', 'high', 'critical'] as const;
type Urgency = (typeof URGENCY_VALUES)[number];

function normalizeUrgency(raw: string): Urgency {
  return (URGENCY_VALUES as readonly string[]).includes(raw)
    ? (raw as Urgency)
    : 'medium';
}

function approvalRequestFromWire(wire: WireApprovalRequest): ApprovalRequest {
  const agentName = wire.agent_name?.trim() || wire.agent_id.slice(0, 8);
  return {
    id: wire.id,
    agentId: wire.agent_id,
    agentName,
    actionCategory: wire.action_category as ActionCategory,
    actionType: wire.action_type,
    payload: wire.payload,
    diff: wire.diff ?? undefined,
    reasoning: wire.reasoning,
    urgency: normalizeUrgency(wire.urgency),
    createdAt: wire.created_at,
  };
}

function resolveWsBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_APPROVALS_WS_URL) return process.env.NEXT_PUBLIC_APPROVALS_WS_URL;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (apiUrl) return apiUrl.replace(/^http/, 'ws') + '/api/v1/approvals/ws';
  return 'ws://localhost:4300/api/v1/approvals/ws';
}
const WS_BASE_URL = resolveWsBaseUrl();

/** Build a per-connection WS URL with the JWT in `?token=`.
 * Per the v2.2.x security pass, /api/v1/approvals/ws requires JWT auth via
 * query param (browsers can't set custom headers on WS upgrade). Returns
 * null when no session token is available — caller skips the connection. */
function buildWsUrl(): string | null {
  const token = getSessionToken();
  if (!token) return null;
  const sep = WS_BASE_URL.includes('?') ? '&' : '?';
  return `${WS_BASE_URL}${sep}token=${encodeURIComponent(token)}`;
}

interface ApprovalsState {
  pendingApprovals: ApprovalRequest[];
  approve: (requestId: string, feedback?: string) => Promise<boolean>;
  deny: (requestId: string, feedback?: string) => Promise<boolean>;
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
  const demo = isDemo();
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [connected, setConnected] = useState(demo);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const wsUrl = buildWsUrl();
    if (!wsUrl) {
      // No session token — likely unauthenticated; skip connection.
      // (Demo mode is already short-circuited above by the caller.)
      return;
    }

    try {
      const ws = new WebSocket(wsUrl);
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
              const request = approvalRequestFromWire(
                message.payload as WireApprovalRequest,
              );
              setPendingApprovals((prev) => {
                // Avoid duplicates
                if (prev.some((a) => a.id === request.id)) return prev;
                return [...prev, request];
              });
              break;
            }

            case 'approval_resolved': {
              // Server broadcasts the same `ApprovalRequestResponse` shape
              // (the now-resolved record). Filter by `id`, not the legacy
              // camelCase `requestId` field that never existed on the wire.
              const resolved = message.payload as WireApprovalRequest;
              setPendingApprovals((prev) =>
                prev.filter((a) => a.id !== resolved.id),
              );
              break;
            }

            case 'approval_batch': {
              const wireBatch = message.payload as WireApprovalRequest[];
              setPendingApprovals(wireBatch.map(approvalRequestFromWire));
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

        if (event.code !== 1000) {
          reconnectAttempts.current++;
          const delay = Math.min(MAX_RECONNECT_DELAY_MS, 1000 * Math.pow(2, reconnectAttempts.current)) + Math.random() * 1000;
          reconnectTimer.current = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        // onclose will fire after onerror, so reconnection is handled there
        setConnected(false);
      };
    } catch {
      setConnected(false);
      reconnectAttempts.current++;
      const delay = Math.min(MAX_RECONNECT_DELAY_MS, 1000 * Math.pow(2, reconnectAttempts.current)) + Math.random() * 1000;
      reconnectTimer.current = setTimeout(connect, delay);
    }
  }, []);

  useEffect(() => {
    if (demo) return; // Skip WebSocket in demo mode
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
    async (requestId: string, decision: 'approve' | 'deny', feedback?: string): Promise<boolean> => {
      // Wire `ApprovalAction` request body — only `feedback` is accepted
      // (the server derives identity + status from JWT + URL path).
      const body: WireApprovalAction = {};
      if (feedback !== undefined) {
        body.feedback = feedback;
      }

      try {
        const res = await apiFetch(`/api/v1/approvals/${requestId}/${decision}`, {
          method: 'POST',
          body: JSON.stringify(body),
        });

        if (res.ok) {
          // Optimistically remove from pending -- the WS will also broadcast the
          // resolution, but removing immediately gives a snappy UI.
          setPendingApprovals((prev) => prev.filter((a) => a.id !== requestId));

          // PostHog analytics
          try {
            const { trackEvent } = await import('@/lib/analytics/posthog');
            trackEvent('selva_approval_responded', { action: decision, request_id: requestId });
          } catch {
            // analytics failure should not affect approval flow
          }

          return true;
        }
        return false;
      } catch {
        return false;
      }
    },
    [],
  );

  const approve = useCallback(
    async (requestId: string, feedback?: string): Promise<boolean> => {
      return sendDecision(requestId, 'approve', feedback);
    },
    [sendDecision],
  );

  const deny = useCallback(
    async (requestId: string, feedback?: string): Promise<boolean> => {
      return sendDecision(requestId, 'deny', feedback);
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
