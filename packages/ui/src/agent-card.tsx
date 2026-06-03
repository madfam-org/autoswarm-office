import type { FC } from 'react';
import type { Agent, AgentRole, AgentStatus } from '@selva/shared-types';
import { cn } from './utils';

export interface AgentCardProps {
  agent: Agent;
}

const roleIcons: Record<AgentRole, string> = {
  planner: '\u{1F4CB}',   // clipboard
  coder: '\u{1F4BB}',     // laptop
  reviewer: '\u{1F50D}',  // magnifying glass
  researcher: '\u{1F4DA}', // books
  crm: '\u{1F4C7}',       // card index
  support: '\u{1F6E0}',   // wrench (hammer & wrench)
};

const roleBadgeColors: Record<AgentRole, string> = {
  planner: 'bg-violet-800 text-violet-200',
  coder: 'bg-cyan-800 text-cyan-200',
  reviewer: 'bg-amber-800 text-amber-200',
  researcher: 'bg-emerald-800 text-emerald-200',
  crm: 'bg-rose-800 text-rose-200',
  support: 'bg-sky-800 text-sky-200',
};

const statusColors: Record<AgentStatus, { dot: string; text: string; bg: string }> = {
  idle: {
    dot: 'bg-gray-400',
    text: 'text-gray-400',
    bg: 'border-gray-600',
  },
  working: {
    dot: 'bg-blue-400 animate-pulse',
    text: 'text-blue-300',
    bg: 'border-blue-500',
  },
  waiting_approval: {
    dot: 'bg-amber-400 animate-pulse',
    text: 'text-amber-300',
    bg: 'border-amber-500',
  },
  paused: {
    dot: 'bg-slate-400',
    text: 'text-slate-400',
    bg: 'border-slate-500',
  },
  error: {
    dot: 'bg-red-500 animate-pulse',
    text: 'text-red-400',
    bg: 'border-red-500',
  },
};

const statusLabels: Record<AgentStatus, string> = {
  idle: 'IDLE',
  working: 'WORKING',
  waiting_approval: 'AWAITING',
  paused: 'PAUSED',
  error: 'ERROR',
};

export const AgentCard: FC<AgentCardProps> = ({ agent }) => {
  const status = statusColors[agent.status];

  return (
    <div
      className={cn(
        'relative w-56 font-mono',
        'bg-slate-900 text-slate-100',
        // 16-bit retro pixel-art border via layered box-shadow
        'shadow-[0_0_0_2px_#000,_0_0_0_4px_#475569,_inset_0_0_0_1px_rgba(255,255,255,0.08)]',
        'border-2',
        status.bg,
        'p-3',
      )}
    >
      {/* Header: Role icon + Name */}
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cn(
            'inline-flex h-8 w-8 items-center justify-center text-lg',
            'shadow-[0_0_0_1px_#000,_inset_0_0_0_1px_rgba(255,255,255,0.1)]',
            roleBadgeColors[agent.role],
          )}
          aria-label={agent.role}
        >
          {roleIcons[agent.role]}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold text-white">{agent.name}</p>
          <p className="text-xs uppercase tracking-wider text-slate-400">
            {agent.role}
          </p>
        </div>
      </div>

      {/* Level bar */}
      <div className="mb-2">
        <div className="mb-0.5 flex items-center justify-between text-xs">
          <span className="text-slate-400">LVL</span>
          <span className="font-bold text-indigo-300">{agent.level}</span>
        </div>
        <div className="h-1.5 w-full bg-slate-800 shadow-[inset_0_0_0_1px_#000]">
          <div
            className="h-full bg-indigo-500"
            style={{ width: `${Math.min(agent.level * 10, 100)}%` }}
          />
        </div>
      </div>

      {/* Status indicator */}
      <div className="mb-2 flex items-center gap-2">
        <span className={cn('inline-block h-2 w-2 rounded-full', status.dot)} />
        <span className={cn('text-xs font-bold uppercase tracking-widest', status.text)}>
          {statusLabels[agent.status]}
        </span>
      </div>

      {/* Synergy badges */}
      {agent.synergyBonuses.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {agent.synergyBonuses.map((synergy) => (
            <span
              key={synergy.name}
              title={`${synergy.description} (x${synergy.multiplier})`}
              className={cn(
                'inline-block px-1.5 py-0.5 text-[10px] font-bold uppercase',
                'bg-fuchsia-900/50 text-fuchsia-300',
                'shadow-[0_0_0_1px_#701a75]',
              )}
            >
              {synergy.name} x{synergy.multiplier}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
