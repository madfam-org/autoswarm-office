'use client';

import { type FC } from 'react';
import type { Department } from '@selva/shared-types';

interface DeskInfoPanelProps {
  open: boolean;
  onClose: () => void;
  assignedAgentId: string;
  deskTitle: string;
  departments: Department[];
}

export const DeskInfoPanel: FC<DeskInfoPanelProps> = ({
  open,
  onClose,
  assignedAgentId,
  deskTitle,
  departments,
}) => {
  if (!open) return null;

  // Find the agent across all departments
  let agent: { name: string; role: string; status: string; skills?: string[] } | null = null;
  for (const dept of departments) {
    const found = dept.agents.find((a) => a.id === assignedAgentId);
    if (found) {
      agent = {
        name: found.name,
        role: found.role,
        status: found.status,
        skills: (found as unknown as Record<string, unknown>).skills as string[] | undefined,
      };
      break;
    }
  }

  const STATUS_COLORS: Record<string, string> = {
    idle: 'text-slate-400',
    working: 'text-cyan-400',
    waiting_approval: 'text-amber-400',
    error: 'text-red-400',
  };

  const STATUS_DOT_COLORS: Record<string, string> = {
    idle: 'bg-slate-400',
    working: 'bg-cyan-400',
    waiting_approval: 'bg-amber-400',
    error: 'bg-red-400',
  };

  return (
    <div className="absolute bottom-20 left-1/2 z-modal -translate-x-1/2 animate-fade-in-up">
      <div className="retro-panel px-6 py-4 min-w-[240px] max-w-[320px]">
        <div className="flex items-center justify-between mb-3">
          <h3 className="pixel-text text-retro-base text-indigo-400 uppercase">
            {deskTitle}
          </h3>
          <button
            onClick={onClose}
            className="pixel-text text-retro-sm text-red-400 hover:text-red-300 cursor-pointer"
            aria-label="Close desk info"
          >
            [X]
          </button>
        </div>

        {agent ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="pixel-text text-retro-sm text-slate-300">
                {agent.name}
              </span>
              <span className="pixel-text text-retro-xs text-slate-500 uppercase">
                {agent.role}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span
                className={`inline-block h-2 w-2 rounded-full ${STATUS_DOT_COLORS[agent.status] ?? 'bg-slate-400'}`}
                aria-hidden="true"
              />
              <span className={`pixel-text text-retro-sm ${STATUS_COLORS[agent.status] ?? 'text-slate-400'}`}>
                {agent.status.replace('_', ' ')}
              </span>
            </div>
            {agent.skills && agent.skills.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {agent.skills.slice(0, 4).map((skill) => (
                  <span
                    key={skill}
                    className="pixel-text text-retro-xs text-slate-500 bg-slate-800 px-1.5 py-0.5"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="pixel-text text-retro-sm text-slate-500">
            {assignedAgentId ? 'Agent not found' : 'Unassigned desk'}
          </p>
        )}
      </div>
    </div>
  );
};
