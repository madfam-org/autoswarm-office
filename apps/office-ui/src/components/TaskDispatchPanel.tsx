'use client';

import { useState, useEffect, useCallback, useRef, type FC } from 'react';
import type { Department } from '@autoswarm/shared-types';
import type { DispatchRequest, DispatchResponse, DispatchStatus } from '@/hooks/useTaskDispatch';
import { gameEventBus } from '@/game/PhaserGame';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';

const GRAPH_TYPES = ['coding', 'research', 'crm', 'sequential', 'parallel'] as const;

interface TaskDispatchPanelProps {
  open: boolean;
  onClose: () => void;
  onDispatch: (request: DispatchRequest) => Promise<DispatchResponse | null>;
  status: DispatchStatus;
  error: string | null;
  lastDispatchedTask: DispatchResponse | null;
  departments: Department[];
  onReset: () => void;
}

export const TaskDispatchPanel: FC<TaskDispatchPanelProps> = ({
  open,
  onClose,
  onDispatch,
  status,
  error,
  lastDispatchedTask,
  departments,
  onReset,
}) => {
  const [visible, setVisible] = useState(false);
  const [description, setDescription] = useState('');
  const [graphType, setGraphType] = useState<DispatchRequest['graph_type']>('sequential');
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [skillsInput, setSkillsInput] = useState('');
  const [agentsExpanded, setAgentsExpanded] = useState(false);
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const descRef = useRef<HTMLTextAreaElement>(null);
  const trapRef = useFocusTrap<HTMLElement>(open);
  const { addToast } = useToast();

  // Slide animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [open]);

  // Toast on status change + auto-clear success after 3s
  useEffect(() => {
    if (status === 'success') {
      addToast('Task dispatched successfully', 'success');
      const timer = setTimeout(() => onReset(), 3000);
      return () => clearTimeout(timer);
    }
  }, [status, onReset, addToast]);

  useEffect(() => {
    if (error) {
      addToast(error, 'error');
    }
  }, [error, addToast]);

  // Suppress game input while text fields focused
  const handleFocus = useCallback(() => {
    gameEventBus.emit('chat-focus', true);
  }, []);
  const handleBlur = useCallback(() => {
    gameEventBus.emit('chat-focus', false);
  }, []);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleBlur();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose, handleBlur]);

  const handleSubmit = useCallback(async () => {
    if (!description.trim() || status === 'submitting') return;

    const request: DispatchRequest = {
      description: description.trim(),
      graph_type: graphType,
    };
    if (selectedAgents.length > 0) {
      request.assigned_agent_ids = selectedAgents;
    }
    const skills = skillsInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (skills.length > 0) {
      request.required_skills = skills;
    }

    const result = await onDispatch(request);
    if (result) {
      setDescription('');
      setSelectedAgents([]);
      setSkillsInput('');
    }
  }, [description, graphType, selectedAgents, skillsInput, status, onDispatch]);

  const toggleAgent = useCallback((agentId: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agentId)
        ? prev.filter((id) => id !== agentId)
        : [...prev, agentId],
    );
  }, []);

  if (!open) return null;

  return (
    <aside
      ref={trapRef}
      className={`fixed right-0 top-0 z-modal h-full w-full max-w-80 transform transition-transform duration-300 sm:w-80 ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-label="Task dispatch panel"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex h-full flex-col bg-slate-900/95 backdrop-blur-sm pixel-border-accent">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <h2 className="pixel-text text-[10px] uppercase tracking-wider text-indigo-400">
            Dispatch Task
          </h2>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            aria-label="Close dispatch panel"
          >
            ESC
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Description */}
          <div>
            <label className="block font-mono text-[8px] uppercase text-slate-500 mb-1">
              Description *
            </label>
            <textarea
              ref={descRef}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onFocus={handleFocus}
              onBlur={handleBlur}
              maxLength={2000}
              rows={3}
              aria-required="true"
              className="w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 font-mono text-[10px] text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none resize-none"
              placeholder="Describe the task..."
            />
            <p className="mt-0.5 font-mono text-[7px] text-slate-600 text-right">
              {description.length}/2000
            </p>
          </div>

          {/* Graph Type */}
          <div>
            <label className="block font-mono text-[8px] uppercase text-slate-500 mb-1">
              Graph Type
            </label>
            <div className="flex flex-wrap gap-1">
              {GRAPH_TYPES.map((type) => (
                <button
                  key={type}
                  onClick={() => setGraphType(type)}
                  className={`rounded px-2 py-1 font-mono text-[8px] uppercase transition-colors ${
                    graphType === type
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:text-white'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Agent Selection (collapsible) */}
          <div>
            <button
              onClick={() => setAgentsExpanded((prev) => !prev)}
              className="flex items-center gap-1 font-mono text-[8px] uppercase text-slate-500 hover:text-slate-300"
            >
              <span>{agentsExpanded ? '-' : '+'}</span>
              Assign Agents (optional)
              {selectedAgents.length > 0 && (
                <span className="text-indigo-400">({selectedAgents.length})</span>
              )}
            </button>
            {agentsExpanded && (
              <div className="mt-2 space-y-2 max-h-48 overflow-y-auto">
                {departments.map((dept) => (
                  <div key={dept.id}>
                    <p className="font-mono text-[7px] uppercase text-slate-600 mb-1">
                      {dept.name}
                    </p>
                    {dept.agents.map((agent) => (
                      <label
                        key={agent.id}
                        className="flex items-center gap-2 px-1 py-0.5 hover:bg-slate-800/60 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedAgents.includes(agent.id)}
                          onChange={() => toggleAgent(agent.id)}
                          className="accent-indigo-500"
                        />
                        <span className="font-mono text-[8px] text-slate-300">
                          {agent.name}
                        </span>
                        <span className="font-mono text-[7px] text-slate-600">
                          {agent.role} / {agent.status}
                        </span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Skill Requirements (collapsible) */}
          <div>
            <button
              onClick={() => setSkillsExpanded((prev) => !prev)}
              className="flex items-center gap-1 font-mono text-[8px] uppercase text-slate-500 hover:text-slate-300"
            >
              <span>{skillsExpanded ? '-' : '+'}</span>
              Required Skills (optional)
            </button>
            {skillsExpanded && (
              <input
                type="text"
                value={skillsInput}
                onChange={(e) => setSkillsInput(e.target.value)}
                onFocus={handleFocus}
                onBlur={handleBlur}
                className="mt-2 w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 font-mono text-[10px] text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                placeholder="coding, review, testing..."
              />
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-slate-700 px-4 py-3 space-y-2">
          {/* Success flash */}
          {status === 'success' && lastDispatchedTask && (
            <p className="font-mono text-[9px] text-emerald-400">
              Task queued: {lastDispatchedTask.id.substring(0, 8)}
            </p>
          )}

          {/* Error message */}
          {error && (
            <p className="font-mono text-[9px] text-red-400">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={!description.trim() || status === 'submitting'}
            className="w-full rounded bg-indigo-600 px-4 py-2 font-mono text-[10px] uppercase text-white transition-colors hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed"
          >
            {status === 'submitting' ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Dispatching...
              </span>
            ) : 'Dispatch'}
          </button>
        </div>
      </div>
    </aside>
  );
};
