'use client';

import { useState, useCallback } from 'react';
import { apiFetch, isDemo } from '@/lib/api';

export interface DispatchRequest {
  title?: string;
  description: string;
  graph_type: 'coding' | 'research' | 'crm' | 'deployment' | 'sequential' | 'parallel' | 'custom' | 'puppeteer' | 'meeting';
  assigned_agent_ids?: string[];
  required_skills?: string[];
  payload?: Record<string, unknown>;
  workflow_id?: string;
  priority?: 'low' | 'medium' | 'high' | 'critical';
  labels?: string[];
  due_date?: string;
}

export interface DispatchResponse {
  id: string;
  title?: string | null;
  description: string;
  graph_type: string;
  status: string;
  kanban_status?: string;
  priority?: string;
  labels?: string[];
  assigned_agent_ids: string[];
  created_at: string;
}

export type DispatchStatus = 'idle' | 'submitting' | 'success' | 'error';

/** Machine-readable code the backend attaches to every budget 402 detail. */
const BUDGET_EXHAUSTED_CODE = 'budget_exhausted';

export function useTaskDispatch(): {
  dispatch: (request: DispatchRequest) => Promise<DispatchResponse | null>;
  status: DispatchStatus;
  error: string | null;
  /** True when the last dispatch was refused for hitting the plan's budget
   *  (HTTP 402). Drives the upgrade modal — the highest-intent conversion
   *  moment: the user hit a wall mid-value. */
  limitReached: boolean;
  /** Human message from the 402 (for the modal body). */
  limitMessage: string | null;
  lastDispatchedTask: DispatchResponse | null;
  reset: () => void;
} {
  const [status, setStatus] = useState<DispatchStatus>('idle');
  const [limitReached, setLimitReached] = useState(false);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastDispatchedTask, setLastDispatchedTask] = useState<DispatchResponse | null>(null);

  const dispatch = useCallback(async (request: DispatchRequest): Promise<DispatchResponse | null> => {
    setStatus('submitting');
    setError(null);
    setLimitReached(false);
    setLimitMessage(null);

    // Demo mode: return mock response after a short delay
    if (isDemo()) {
      await new Promise((r) => setTimeout(r, 800));
      const mock: DispatchResponse = {
        id: `demo-task-${Date.now()}`,
        title: request.title ?? null,
        description: request.description,
        graph_type: request.graph_type,
        status: 'queued',
        kanban_status: 'todo',
        priority: request.priority ?? 'medium',
        labels: request.labels ?? [],
        assigned_agent_ids: [],
        created_at: new Date().toISOString(),
      };
      setLastDispatchedTask(mock);
      setStatus('success');
      return mock;
    }

    try {
      const res = await apiFetch('/api/v1/swarms/dispatch', {
        method: 'POST',
        body: JSON.stringify(request),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = (body as Record<string, unknown>).detail;

        // 402 with the budget_exhausted code → the upgrade moment, not a
        // generic error. detail is a structured {code, message} object.
        if (
          res.status === 402 &&
          typeof detail === 'object' &&
          detail !== null &&
          (detail as Record<string, unknown>).code === BUDGET_EXHAUSTED_CODE
        ) {
          const msg = (detail as Record<string, unknown>).message;
          setLimitMessage(typeof msg === 'string' ? msg : null);
          setLimitReached(true);
          setStatus('error');
          return null;
        }

        setError(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
        setStatus('error');
        return null;
      }

      const data = (await res.json()) as DispatchResponse;
      setLastDispatchedTask(data);
      setStatus('success');

      // PostHog analytics
      try {
        const { trackEvent } = await import('@/lib/analytics/posthog');
        trackEvent('selva_task_submitted', { graph_type: request.graph_type });
      } catch {
        // analytics failure should not affect dispatch
      }

      return data;
    } catch {
      setError('Network error — could not reach server');
      setStatus('error');
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setStatus('idle');
    setError(null);
    setLimitReached(false);
    setLimitMessage(null);
    setLastDispatchedTask(null);
  }, []);

  return { dispatch, status, error, limitReached, limitMessage, lastDispatchedTask, reset };
}
