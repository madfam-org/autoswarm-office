'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  listScheduledActions,
  updateScheduledActionHitl,
} from '@/components/campaigns/api';
import type { ScheduledActionRow } from '@/components/campaigns/types';
import { isDemo } from '@/lib/api';

const POLL_INTERVAL_MS = 15000;

interface ScheduledActionsState {
  actions: ScheduledActionRow[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  approve: (actionId: string) => Promise<boolean>;
  deny: (actionId: string) => Promise<boolean>;
}

export function useScheduledActions(statusFilter?: string): ScheduledActionsState {
  const [actions, setActions] = useState<ScheduledActionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const refresh = useCallback(async () => {
    if (isDemo()) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await listScheduledActions(statusFilter);
      setActions(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load scheduled actions');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (isDemo()) return undefined;
    void refresh();
    pollRef.current = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  const approve = useCallback(
    async (actionId: string) => {
      try {
        await updateScheduledActionHitl(actionId, 'approved');
        await refresh();
        return true;
      } catch {
        return false;
      }
    },
    [refresh],
  );

  const deny = useCallback(
    async (actionId: string) => {
      try {
        await updateScheduledActionHitl(actionId, 'denied');
        await refresh();
        return true;
      } catch {
        return false;
      }
    },
    [refresh],
  );

  return { actions, loading, error, refresh, approve, deny };
}
