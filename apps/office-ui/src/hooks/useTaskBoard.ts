'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { KanbanStatus, TaskBoardResponse, WireTaskTimeline } from '@selva/shared-types';
import { apiFetch, isDemo } from '@/lib/api';

const POLL_INTERVAL_MS = 10000;

interface TaskBoardState {
  // Wire shape from /api/v1/swarms/tasks/board (snake_case). Consumers
  // (DashboardPanel) already read snake_case fields, so no conversion
  // happens at the boundary — the previous hand-written `TaskBoardResponse`
  // domain type was already a shadow of the wire shape.
  board: TaskBoardResponse | null;
  loading: boolean;
  selectedTimeline: WireTaskTimeline | null;
  timelineLoading: boolean;
  selectTask: (taskId: string) => Promise<void>;
  clearSelection: () => void;
  refresh: () => Promise<void>;
  moveTask: (taskId: string, kanbanStatus: KanbanStatus) => Promise<void>;
}

/**
 * React hook for the DB-backed task board.
 * Polls /api/v1/swarms/tasks/board every 10s and provides
 * task timeline loading for the detail view.
 */
export function useTaskBoard(): TaskBoardState {
  const [board, setBoard] = useState<TaskBoardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTimeline, setSelectedTimeline] = useState<WireTaskTimeline | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const fetchBoard = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiFetch('/api/v1/swarms/tasks/board');
      if (res.ok) {
        const data = (await res.json()) as TaskBoardResponse;
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

  const moveTask = useCallback(async (taskId: string, kanbanStatus: KanbanStatus) => {
    setBoard((prev) => {
      if (!prev) return prev;
      const nextColumns = Object.fromEntries(
        Object.entries(prev.columns).map(([status, tasks]) => [
          status,
          tasks.filter((task) => task.id !== taskId),
        ]),
      ) as TaskBoardResponse['columns'];
      const movedTask = Object.values(prev.columns).flat().find((task) => task.id === taskId);
      if (movedTask) {
        nextColumns[kanbanStatus] = [
          { ...movedTask, kanban_status: kanbanStatus },
          ...(nextColumns[kanbanStatus] ?? []),
        ];
      }
      return {
        ...prev,
        columns: nextColumns,
        totals: Object.fromEntries(
          Object.entries(nextColumns).map(([status, tasks]) => [status, tasks.length]),
        ),
      };
    });

    const res = await apiFetch(`/api/v1/swarms/tasks/${taskId}/kanban`, {
      method: 'PATCH',
      body: JSON.stringify({ kanban_status: kanbanStatus }),
    });
    if (!res.ok) {
      await fetchBoard();
    }
  }, [fetchBoard]);

  return {
    board,
    loading,
    selectedTimeline,
    timelineLoading,
    selectTask,
    clearSelection,
    refresh: fetchBoard,
    moveTask,
  };
}
