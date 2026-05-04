'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { WireTaskBoardResponse, WireTaskTimeline } from '@autoswarm/shared-types';
import { apiFetch, isDemo } from '@/lib/api';

const POLL_INTERVAL_MS = 10000;

interface TaskBoardState {
  // Wire shape from /api/v1/swarms/tasks/board (snake_case). Consumers
  // (DashboardPanel) already read snake_case fields, so no conversion
  // happens at the boundary — the previous hand-written `TaskBoardResponse`
  // domain type was already a shadow of the wire shape.
  board: WireTaskBoardResponse | null;
  loading: boolean;
  selectedTimeline: WireTaskTimeline | null;
  timelineLoading: boolean;
  selectTask: (taskId: string) => Promise<void>;
  clearSelection: () => void;
  refresh: () => Promise<void>;
}

/**
 * React hook for the DB-backed task board.
 * Polls /api/v1/swarms/tasks/board every 10s and provides
 * task timeline loading for the detail view.
 */
export function useTaskBoard(): TaskBoardState {
  const [board, setBoard] = useState<WireTaskBoardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTimeline, setSelectedTimeline] = useState<WireTaskTimeline | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const fetchBoard = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiFetch('/api/v1/swarms/tasks/board');
      if (res.ok) {
        const data = (await res.json()) as WireTaskBoardResponse;
        setBoard(data);
      }
    } catch {
      // Silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  const demo = isDemo();
  useEffect(() => {
    if (demo) return; // Skip API polling in demo mode
    void fetchBoard();
    pollRef.current = setInterval(() => void fetchBoard(), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchBoard, demo]);

  const selectTask = useCallback(async (taskId: string) => {
    setTimelineLoading(true);
    try {
      const res = await apiFetch(`/api/v1/events/tasks/${taskId}/timeline`);
      if (res.ok) {
        const data = (await res.json()) as WireTaskTimeline;
        setSelectedTimeline(data);
      }
    } catch {
      // Silently fail
    } finally {
      setTimelineLoading(false);
    }
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedTimeline(null);
  }, []);

  return {
    board,
    loading,
    selectedTimeline,
    timelineLoading,
    selectTask,
    clearSelection,
    refresh: fetchBoard,
  };
}
