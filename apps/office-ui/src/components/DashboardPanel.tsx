'use client';

import { useState, useEffect, type FC } from 'react';
import type {
  Department,
  Agent,
  KanbanStatus,
  TaskBoardItem,
  WireTaskTimeline,
} from '@autoswarm/shared-types';
import { useTaskBoard } from '@/hooks/useTaskBoard';
import { formatHMS } from '@/lib/format-time';

interface DashboardPanelProps {
  open: boolean;
  onToggle: () => void;
  departments: Department[];
  onNewTask?: () => void;
  onOpenMarketplace?: () => void;
  onOpenCampaigns?: () => void;
  onOpenMapEditor?: () => void;
}

const DEPARTMENT_ICONS: Record<string, string> = {
  engineering: '\uD83D\uDD27',
  sales: '\uD83D\uDCCA',
  support: '\uD83C\uDFA7',
  research: '\uD83D\uDD2C',
  blueprint: '\uD83D\uDCD0',
};

const STATUS_COLUMNS: {
  key: KanbanStatus;
  label: string;
  color: string;
  borderColor: string;
}[] = [
  { key: 'todo', label: 'TODO', color: 'text-slate-400', borderColor: '#64748b' },
  { key: 'in_progress', label: 'IN PROGRESS', color: 'text-blue-400', borderColor: '#3b82f6' },
  { key: 'review', label: 'REVIEW', color: 'text-amber-400', borderColor: '#f59e0b' },
  { key: 'done', label: 'DONE', color: 'text-emerald-400', borderColor: '#10b981' },
  { key: 'blocked', label: 'BLOCKED', color: 'text-red-400', borderColor: '#ef4444' },
];

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

const TaskTimelineView: FC<{
  timeline: WireTaskTimeline;
  onClose: () => void;
}> = ({ timeline, onClose }) => (
  <div className="border-b border-slate-700 px-3 py-2">
    <div className="flex items-center justify-between mb-2">
      <h3 className="pixel-text text-[7px] uppercase text-indigo-400">
        Timeline ({timeline.events.length} events)
      </h3>
      <button
        onClick={onClose}
        className="font-mono text-[8px] text-slate-500 hover:text-white"
      >
        [close]
      </button>
    </div>
    <div className="flex gap-2 mb-2 font-mono text-[7px] text-slate-500">
      {timeline.total_duration_ms != null && (
        <span>Total: {formatDuration(timeline.total_duration_ms)}</span>
      )}
      {timeline.total_tokens != null && (
        <span>{timeline.total_tokens.toLocaleString()} tokens</span>
      )}
    </div>
    <div className="max-h-40 overflow-y-auto space-y-0.5">
      {timeline.events.map((ev) => (
        <div
          key={ev.id}
          className="flex items-center gap-1 font-mono text-[7px] py-0.5 border-l-2 pl-1"
          style={{
            borderColor: ev.event_type.includes('error') ? '#ef4444'
              : ev.event_category === 'llm' ? '#a855f7'
              : ev.event_category === 'node' ? '#22d3ee'
              : '#64748b',
          }}
        >
          <span className="text-slate-500 w-14 shrink-0">
            {formatHMS(ev.created_at)}
          </span>
          <span className={ev.event_type.includes('error') ? 'text-red-400' : 'text-slate-300'}>
            {ev.event_type}
          </span>
          {ev.node_id && <span className="text-cyan-400">[{ev.node_id}]</span>}
          {ev.duration_ms != null && (
            <span className="text-slate-600">{formatDuration(ev.duration_ms)}</span>
          )}
        </div>
      ))}
    </div>
  </div>
);

const TaskCard: FC<{
  task: TaskBoardItem;
  borderColor: string;
  index: number;
  onSelect: (id: string) => void;
  onDragStart: (id: string) => void;
}> = ({ task, borderColor, index, onSelect, onDragStart }) => (
  <div
    draggable
    onDragStart={() => onDragStart(task.id)}
    onClick={() => onSelect(task.id)}
    className="bg-slate-800/60 px-2 py-1.5 font-mono text-[8px] shadow-[0_0_0_1px_#334155] transition-all duration-150 hover:bg-slate-700/60 hover:translate-x-1 cursor-pointer animate-fade-in-up"
    style={{
      borderLeft: `2px solid ${borderColor}`,
      animationDelay: `${index * 50}ms`,
    }}
  >
    <div className="flex items-center justify-between">
      <p className="truncate text-slate-200 flex-1 min-w-0">
        {(task.title || task.description).length > 50
          ? (task.title || task.description).substring(0, 50) + '...'
          : task.title || task.description}
      </p>
      <span className="ml-1 rounded bg-slate-700 px-1 text-[6px] text-slate-400 uppercase">
        {task.graph_type}
      </span>
    </div>
    <div className="flex items-center gap-2 mt-0.5">
      <span className="text-amber-300 uppercase">{task.priority}</span>
      {task.labels.slice(0, 2).map((label) => (
        <span key={label} className="rounded bg-slate-700 px-1 text-[6px] text-slate-300">
          {label}
        </span>
      ))}
      {task.agent_names.length > 0 && (
        <span className="text-cyan-400">{task.agent_names.join(', ')}</span>
      )}
      {task.duration_ms != null && (
        <span className="text-slate-500">{formatDuration(task.duration_ms)}</span>
      )}
      {task.total_tokens != null && task.total_tokens > 0 && (
        <span className="text-purple-400">{task.total_tokens} tok</span>
      )}
      {task.event_count > 0 && (
        <span className="text-slate-600">{task.event_count} events</span>
      )}
      {task.comment_count > 0 && (
        <span className="text-slate-500">{task.comment_count} comments</span>
      )}
    </div>
  </div>
);

export const DashboardPanel: FC<DashboardPanelProps> = ({
  open,
  onToggle,
  departments,
  onNewTask,
  onOpenMarketplace,
  onOpenCampaigns,
  onOpenMapEditor,
}) => {
  const [selectedDepartment, setSelectedDepartment] = useState<string | null>(null);
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const { board, selectedTimeline, timelineLoading, selectTask, clearSelection, moveTask } = useTaskBoard();

  // Listen for postMessage events from other components
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'dashboard:select-department') {
        setSelectedDepartment(event.data.departmentSlug as string);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  const handleSelectTask = (taskId: string) => {
    void selectTask(taskId);
  };

  const handleDropTask = (statusKey: KanbanStatus) => {
    if (!draggedTaskId) return;
    void moveTask(draggedTaskId, statusKey);
    setDraggedTaskId(null);
  };

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="pointer-events-auto absolute right-0 top-1/2 z-video -translate-y-1/2 retro-panel retro-btn px-1.5 sm:px-2 py-6 sm:py-8 border border-r-0 border-slate-700/50 rounded-l-lg font-mono text-sm sm:text-[10px] text-slate-400 transition-all hover:text-white hover:bg-slate-700/50"
        aria-label={open ? 'Close dashboard panel' : 'Open dashboard panel'}
        aria-expanded={open}
      >
        {open ? '>' : '<'}
      </button>

      {/* Backdrop overlay when open */}
      {open && (
        <div
          className="fixed inset-0 z-backdrop-below-hud bg-black/20 animate-fade-in"
          onClick={onToggle}
        />
      )}

      {/* Sliding panel */}
      <aside
        className={`absolute right-0 top-0 z-hud h-full w-full max-w-80 landscape:max-h-[70vh] transform transition-transform duration-300 sm:w-80 md:max-w-96 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
        aria-label="Dashboard panel"
        role="complementary"
      >
        <div className="flex h-full flex-col bg-slate-900/95 backdrop-blur-sm pixel-border-accent">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
            <h2 className="pixel-text text-[10px] uppercase tracking-wider text-indigo-400">
              Dashboard
            </h2>
            <div className="flex gap-1.5">
              {onOpenMarketplace && (
                <button
                  onClick={onOpenMarketplace}
                  className="touch-target rounded bg-purple-600 px-2 py-1 font-mono text-[8px] text-white hover:bg-purple-500 transition-colors"
                  aria-label="Open skill marketplace"
                >
                  Skills
                </button>
              )}
              {onOpenCampaigns && (
                <button
                  onClick={onOpenCampaigns}
                  className="touch-target rounded bg-rose-700 px-2 py-1 font-mono text-[8px] text-white hover:bg-rose-600 transition-colors"
                  aria-label="Open campaign dashboard"
                >
                  Campaigns
                </button>
              )}
              {onOpenMapEditor && (
                <button
                  onClick={onOpenMapEditor}
                  className="touch-target rounded bg-teal-600 px-2 py-1 font-mono text-[8px] text-white hover:bg-teal-500 transition-colors"
                  aria-label="Open map editor"
                >
                  Map Editor
                </button>
              )}
              {onNewTask && (
                <button
                  onClick={onNewTask}
                  className="touch-target rounded bg-indigo-600 px-2 py-1 font-mono text-[8px] text-white hover:bg-indigo-500 transition-colors"
                  aria-label="Dispatch new task"
                >
                  + New Task
                </button>
              )}
            </div>
          </div>

          {/* Department filter tabs */}
          <div className="flex gap-1 overflow-x-auto border-b border-slate-800 px-3 py-2">
            <button
              onClick={() => setSelectedDepartment(null)}
              className={`whitespace-nowrap px-2 py-1 font-mono text-[8px] uppercase transition-colors ${
                !selectedDepartment
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              All
            </button>
            {departments.map((dept) => (
              <button
                key={dept.id}
                onClick={() => setSelectedDepartment(dept.slug)}
                className={`whitespace-nowrap px-2 py-1 font-mono text-[8px] uppercase transition-colors ${
                  selectedDepartment === dept.slug
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:text-white'
                }`}
              >
                {DEPARTMENT_ICONS[dept.slug] && (
                  <span className="mr-0.5">{DEPARTMENT_ICONS[dept.slug]}</span>
                )}
                {dept.name}
              </button>
            ))}
          </div>

          {/* Department stats */}
          <div className="border-b border-slate-800 px-4 py-3">
            <div className="grid grid-cols-3 gap-2">
              {departments
                .filter(
                  (d) => !selectedDepartment || d.slug === selectedDepartment,
                )
                .map((dept) => {
                  const deptAgentCount = dept.agents.length;
                  const deptTaskCount = dept.agents.filter(
                    (a: Agent) => a.currentTaskId,
                  ).length;
                  const synergyCount = dept.agents.reduce(
                    (sum: number, a: Agent) => sum + (a.synergyBonuses?.length ?? 0),
                    0,
                  );

                  const agentPercent = dept.maxAgents > 0 ? (deptAgentCount / dept.maxAgents) * 100 : 0;
                  return (
                    <div
                      key={dept.id}
                      className="retro-panel px-2 py-2 text-center animate-fade-in-up"
                      style={{ animationDelay: `${departments.indexOf(dept) * 50}ms` }}
                    >
                      <p className="pixel-text text-[6px] uppercase text-slate-500">
                        {DEPARTMENT_ICONS[dept.slug] && (
                          <span className="mr-0.5">{DEPARTMENT_ICONS[dept.slug]}</span>
                        )}
                        {dept.name.substring(0, 5)}
                      </p>
                      <div className="mt-1 space-y-0.5 font-mono text-[9px]">
                        <p className="text-cyan-400">
                          {deptAgentCount}/{dept.maxAgents} agents
                        </p>
                        <div className="h-1 w-full bg-slate-900 rounded-full mt-0.5">
                          <div
                            className="h-full bg-cyan-500 rounded-full transition-all duration-500"
                            style={{ width: `${agentPercent}%` }}
                          />
                        </div>
                        <p className="text-amber-400">{deptTaskCount} tasks</p>
                        <div className="h-1 w-full bg-slate-900 rounded-full">
                          <div
                            className="h-full bg-amber-500 rounded-full transition-all duration-500"
                            style={{ width: `${deptAgentCount > 0 ? (deptTaskCount / deptAgentCount) * 100 : 0}%` }}
                          />
                        </div>
                        {synergyCount > 0 && (
                          <p className="text-fuchsia-400">
                            {synergyCount} synergy
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>

          {/* Active Agents */}
          {(() => {
            const workingAgents = departments.flatMap((dept) =>
              dept.agents
                .filter((a: Agent) => a.status === 'working')
                .map((a: Agent) => ({ ...a, deptSlug: dept.slug })),
            );
            if (workingAgents.length === 0) return null;
            return (
              <div className="border-b border-slate-800 px-4 py-2">
                <h3 className="pixel-text text-[7px] uppercase text-slate-500 mb-1">
                  Active Agents
                </h3>
                {workingAgents.map((agent) => (
                  <div
                    key={agent.id}
                    className="flex items-center justify-between font-mono text-[8px] py-0.5"
                  >
                    <span className="text-cyan-400">{agent.name}</span>
                    <span className="text-slate-500">
                      [{agent.currentNodeId || 'init'}]
                    </span>
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Task timeline detail view */}
          {timelineLoading && (
            <div className="border-b border-slate-700 px-3 py-4 text-center font-mono text-[8px] text-slate-500">
              Loading timeline...
            </div>
          )}
          {selectedTimeline && !timelineLoading && (
            <TaskTimelineView timeline={selectedTimeline} onClose={clearSelection} />
          )}

          {/* DB-backed Kanban columns */}
          <div className="flex-1 overflow-y-auto px-3 py-3" aria-live="polite">
            <div className="space-y-3">
              {STATUS_COLUMNS.map((column) => {
                const columnTasks = board?.columns[column.key] ?? [];

                return (
                  <div
                    key={column.key}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => handleDropTask(column.key)}
                    className="rounded border border-transparent px-1 py-1 transition-colors hover:border-slate-700/60"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <h3
                        className={`pixel-text text-[7px] uppercase ${column.color}`}
                      >
                        {column.label}
                      </h3>
                      <span className="font-mono text-[9px] text-slate-600">
                        ({columnTasks.length})
                      </span>
                    </div>

                    {columnTasks.length === 0 ? (
                      <p className="py-2 text-center font-mono text-[8px] text-slate-600 italic">
                        No tasks yet
                      </p>
                    ) : (
                      <div className="space-y-1">
                        {columnTasks.map((task, taskIdx) => (
                          <TaskCard
                            key={task.id}
                            task={task}
                            borderColor={column.borderColor}
                            index={taskIdx}
                            onSelect={handleSelectTask}
                            onDragStart={setDraggedTaskId}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
