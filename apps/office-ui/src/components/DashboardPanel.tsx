'use client';

import { useState, useEffect, type FC } from 'react';
import type { Department, Agent } from '@autoswarm/shared-types';

interface DashboardPanelProps {
  open: boolean;
  onToggle: () => void;
  departments: Department[];
  onNewTask?: () => void;
}

type TaskStatus = 'backlog' | 'in_progress' | 'review' | 'done';

interface KanbanTask {
  id: string;
  agentName: string;
  title: string;
  status: TaskStatus;
  departmentSlug: string;
}

const STATUS_COLUMNS: { key: TaskStatus; label: string; color: string }[] = [
  { key: 'backlog', label: 'BACKLOG', color: 'text-slate-400' },
  { key: 'in_progress', label: 'IN PROGRESS', color: 'text-blue-400' },
  { key: 'review', label: 'REVIEW', color: 'text-amber-400' },
  { key: 'done', label: 'DONE', color: 'text-emerald-400' },
];

/**
 * Derive kanban tasks from agent statuses.
 * Maps agent status to a kanban column for visualization.
 */
function deriveTasksFromAgents(departments: Department[]): KanbanTask[] {
  const tasks: KanbanTask[] = [];

  departments.forEach((dept) => {
    dept.agents.forEach((agent: Agent) => {
      if (!agent.currentTaskId) return;

      let status: TaskStatus = 'backlog';
      switch (agent.status) {
        case 'working':
          status = 'in_progress';
          break;
        case 'waiting_approval':
          status = 'review';
          break;
        case 'idle':
          status = agent.currentTaskId ? 'done' : 'backlog';
          break;
        case 'paused':
        case 'error':
          status = 'backlog';
          break;
      }

      tasks.push({
        id: agent.currentTaskId,
        agentName: agent.name,
        title: `Task ${agent.currentTaskId.substring(0, 8)}`,
        status,
        departmentSlug: dept.slug,
      });
    });
  });

  return tasks;
}

export const DashboardPanel: FC<DashboardPanelProps> = ({
  open,
  onToggle,
  departments,
  onNewTask,
}) => {
  const [selectedDepartment, setSelectedDepartment] = useState<string | null>(null);
  const tasks = deriveTasksFromAgents(departments);

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

  const filteredTasks = selectedDepartment
    ? tasks.filter((t) => t.departmentSlug === selectedDepartment)
    : tasks;

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="pointer-events-auto absolute right-0 top-1/2 z-video -translate-y-1/2 retro-panel retro-btn px-2 py-6 font-mono text-[10px] text-slate-400 transition-all hover:text-white"
        aria-label={open ? 'Close dashboard panel' : 'Open dashboard panel'}
        aria-expanded={open}
      >
        {open ? '>' : '<'}
      </button>

      {/* Backdrop overlay when open */}
      {open && (
        <div
          className="fixed inset-0 z-[19] bg-black/20 animate-fade-in"
          onClick={onToggle}
        />
      )}

      {/* Sliding panel */}
      <aside
        className={`absolute right-0 top-0 z-hud h-full w-full max-w-80 transform transition-transform duration-300 sm:w-80 ${
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
            {onNewTask && (
              <button
                onClick={onNewTask}
                className="rounded bg-indigo-600 px-2 py-1 font-mono text-[8px] text-white hover:bg-indigo-500 transition-colors"
              >
                + New Task
              </button>
            )}
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
                    (a) => a.currentTaskId,
                  ).length;
                  const synergyCount = dept.agents.reduce(
                    (sum, a) => sum + a.synergyBonuses.length,
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

          {/* Kanban columns */}
          <div className="flex-1 overflow-y-auto px-3 py-3">
            <div className="space-y-3">
              {STATUS_COLUMNS.map((column) => {
                const columnTasks = filteredTasks.filter(
                  (t) => t.status === column.key,
                );

                return (
                  <div key={column.key}>
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
                          <div
                            key={task.id}
                            className="flex items-center justify-between bg-slate-800/60 px-2 py-1.5 font-mono text-[8px] shadow-[0_0_0_1px_#334155] transition-all duration-150 hover:bg-slate-700/60 hover:translate-x-1 cursor-default animate-fade-in-up"
                            style={{
                              borderLeft: `2px solid ${column.key === 'in_progress' ? '#3b82f6' : column.key === 'review' ? '#f59e0b' : column.key === 'done' ? '#10b981' : '#64748b'}`,
                              animationDelay: `${taskIdx * 50}ms`,
                            }}
                          >
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-slate-200">
                                {task.title}
                              </p>
                              <p className="text-slate-500">
                                {task.agentName}
                              </p>
                            </div>
                          </div>
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
