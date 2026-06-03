'use client';

import { useState, useEffect, useRef } from 'react';
import type { OfficeState } from '@selva/shared-types';

export interface ExecutionEvent {
  timestamp: number;
  nodeId: string;
  agentName: string;
  agentId: string;
  type: 'started' | 'completed';
}

/**
 * Watches Colyseus office state for currentNodeId changes on agents
 * and accumulates a chronological execution log.
 */
export function useExecutionLog(officeState: OfficeState | null) {
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const prevNodeIds = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    if (!officeState?.departments) return;

    const newMap = new Map<string, string>();

    for (const dept of officeState.departments) {
      if (!dept.agents) continue;
      for (const agent of dept.agents) {
        const nodeId = (agent as unknown as Record<string, unknown>).currentNodeId as string | undefined;
        const prevNodeId = prevNodeIds.current.get(agent.id);

        newMap.set(agent.id, nodeId ?? '');

        if (nodeId && nodeId !== prevNodeId) {
          // New node started
          if (prevNodeId) {
            setEvents((prev) => [
              ...prev,
              {
                timestamp: Date.now(),
                nodeId: prevNodeId,
                agentName: agent.name,
                agentId: agent.id,
                type: 'completed',
              },
            ]);
          }
          setEvents((prev) => [
            ...prev,
            {
              timestamp: Date.now(),
              nodeId,
              agentName: agent.name,
              agentId: agent.id,
              type: 'started',
            },
          ]);
        } else if (!nodeId && prevNodeId) {
          // Node completed (agent returned to no node)
          setEvents((prev) => [
            ...prev,
            {
              timestamp: Date.now(),
              nodeId: prevNodeId,
              agentName: agent.name,
              agentId: agent.id,
              type: 'completed',
            },
          ]);
        }
      }
    }

    prevNodeIds.current = newMap;
  }, [officeState]);

  const clearEvents = () => setEvents([]);

  return { events, clearEvents };
}
