'use client';

import { useState, useRef, useEffect, useCallback, type FC } from 'react';
import type { Department, Agent, ApprovalRequest, ChatMessage } from '@autoswarm/shared-types';
import { formatHM } from '@/lib/format-time';

const STATUS_COLORS: Record<string, string> = {
  idle: 'bg-slate-400',
  working: 'bg-cyan-400',
  waiting_approval: 'bg-amber-400',
  paused: 'bg-violet-400',
  error: 'bg-red-500',
};

const STATUS_LABELS: Record<string, string> = {
  idle: 'Idle',
  working: 'Working',
  waiting_approval: 'Awaiting Approval',
  paused: 'Paused',
  error: 'Error',
};

const URGENCY_STYLES: Record<string, string> = {
  low: 'text-slate-400 bg-slate-800',
  medium: 'text-amber-300 bg-amber-900/40',
  high: 'text-orange-300 bg-orange-900/40',
  critical: 'text-red-300 bg-red-900/40',
};

function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_COLORS[status] ?? 'bg-slate-400'}`}
      aria-label={STATUS_LABELS[status] ?? status}
    />
  );
}

interface SimplifiedViewProps {
  departments: Department[];
  pendingApprovals: ApprovalRequest[];
  chatMessages: ChatMessage[];
  onSendChat: (content: string) => void;
  onApprove: (requestId: string, feedback?: string) => Promise<boolean>;
  onDeny: (requestId: string, feedback?: string) => Promise<boolean>;
  onDispatchTask: () => void;
  onOpenMarketplace?: () => void;
  onToggleViewMode: () => void;
  colyseusConnected: boolean;
  approvalsConnected: boolean;
}

export const SimplifiedView: FC<SimplifiedViewProps> = ({
  departments,
  pendingApprovals,
  chatMessages,
  onSendChat,
  onApprove,
  onDeny,
  onDispatchTask,
  onOpenMarketplace,
  onToggleViewMode,
  colyseusConnected,
  approvalsConnected,
}) => {
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll chat on new messages
  useEffect(() => {
    if (chatEndRef.current && typeof chatEndRef.current.scrollIntoView === 'function') {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [chatMessages.length]);

  const handleChatSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = chatInput.trim();
      if (!trimmed) return;
      onSendChat(trimmed);
      setChatInput('');
    },
    [chatInput, onSendChat],
  );

  const totalAgents = departments.reduce((sum, d) => sum + d.agents.length, 0);

  return (
    <div className="flex h-full flex-col bg-slate-900 text-slate-200" role="main" aria-label="AutoSwarm Office - Simplified View">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-slate-700 bg-slate-900/95 px-4 py-3">
        <div className="flex items-center gap-3">
          <h1 className="pixel-text text-[12px] uppercase tracking-wider text-indigo-400">
            AutoSwarm Office
          </h1>
          <div className="flex items-center gap-2 font-mono text-[8px]">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                colyseusConnected ? 'bg-emerald-400' : 'bg-red-500'
              }`}
              aria-label={colyseusConnected ? 'Room connected' : 'Room disconnected'}
            />
            <span className="text-slate-500">Room</span>
            <span
              className={`ml-1 inline-block h-2 w-2 rounded-full ${
                approvalsConnected ? 'bg-emerald-400' : 'bg-red-500'
              }`}
              aria-label={approvalsConnected ? 'API connected' : 'API disconnected'}
            />
            <span className="text-slate-500">API</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onOpenMarketplace && (
            <button
              onClick={onOpenMarketplace}
              className="rounded bg-purple-600 px-2 py-1 font-mono text-[8px] text-white transition-colors hover:bg-purple-500"
            >
              Skills
            </button>
          )}
          <button
            onClick={onDispatchTask}
            className="rounded bg-indigo-600 px-2 py-1 font-mono text-[8px] text-white transition-colors hover:bg-indigo-500"
          >
            + New Task
          </button>
          <button
            onClick={onToggleViewMode}
            className="rounded bg-slate-700 px-3 py-1 font-mono text-[8px] text-slate-300 transition-colors hover:bg-slate-600 hover:text-white"
            aria-label="Switch to game view"
          >
            Game View
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4 lg:flex-row">
        {/* Left column: Departments */}
        <div className="flex-1 min-w-0">
          <section aria-label="Departments">
            <h2 className="pixel-text mb-3 text-[10px] uppercase tracking-wider text-slate-400">
              Departments
              <span className="ml-2 font-mono text-[9px] text-cyan-400">
                {totalAgents} agents
              </span>
            </h2>

            {departments.length === 0 ? (
              <div className="retro-panel p-6 text-center">
                <p className="font-mono text-[10px] italic text-slate-600">
                  No departments available
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {departments.map((dept) => (
                  <article
                    key={dept.id}
                    className="retro-panel p-4 animate-fade-in"
                    aria-label={`${dept.name} department`}
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="pixel-text text-[9px] uppercase text-indigo-400">
                        {dept.name}
                      </h3>
                      <span className="font-mono text-[8px] text-slate-500">
                        {dept.agents.length}/{dept.maxAgents}
                      </span>
                    </div>

                    {/* Agent capacity bar */}
                    <div className="mb-3 h-1 w-full rounded-full bg-slate-800">
                      <div
                        className="h-full rounded-full bg-cyan-500 transition-all duration-500"
                        style={{
                          width: `${dept.maxAgents > 0 ? (dept.agents.length / dept.maxAgents) * 100 : 0}%`,
                        }}
                      />
                    </div>

                    {dept.agents.length === 0 ? (
                      <p className="font-mono text-[8px] italic text-slate-600">
                        No agents assigned
                      </p>
                    ) : (
                      <ul className="space-y-1.5" aria-label={`Agents in ${dept.name}`}>
                        {dept.agents.map((agent: Agent) => (
                          <li
                            key={agent.id}
                            className="flex items-center gap-2 font-mono text-[9px]"
                          >
                            <StatusDot status={agent.status} />
                            <span className="text-slate-200">{agent.name}</span>
                            <span className="text-slate-500">({agent.role})</span>
                            {agent.currentTaskId && (
                              <span className="ml-auto text-cyan-400">
                                {agent.currentNodeId
                                  ? `[${agent.currentNodeId}]`
                                  : 'Working'}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right column: Approvals + Chat */}
        <div className="flex w-full flex-col gap-4 lg:w-80 lg:shrink-0">
          {/* Approval Queue */}
          <section aria-label="Pending Approvals">
            <h2 className="pixel-text mb-3 text-[10px] uppercase tracking-wider text-slate-400">
              Approvals
              {pendingApprovals.length > 0 && (
                <span className="ml-2 font-mono text-[9px] text-amber-400">
                  {pendingApprovals.length} pending
                </span>
              )}
            </h2>

            {pendingApprovals.length === 0 ? (
              <div className="retro-panel p-4 text-center">
                <p className="font-mono text-[10px] italic text-slate-600">
                  No pending approvals
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {pendingApprovals.map((approval) => (
                  <div
                    key={approval.id}
                    className="retro-panel p-3 animate-fade-in-up"
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <span className="font-mono text-[9px] text-cyan-400">
                        {approval.agentName}
                      </span>
                      <span className="font-mono text-[8px] text-slate-500">
                        {approval.actionCategory}
                      </span>
                      <span
                        className={`ml-auto px-1.5 py-0.5 font-mono text-[7px] uppercase ${URGENCY_STYLES[approval.urgency] ?? URGENCY_STYLES.low}`}
                      >
                        {approval.urgency}
                      </span>
                    </div>
                    <p className="mb-2 font-mono text-[8px] text-slate-400">
                      {approval.reasoning.length > 120
                        ? `${approval.reasoning.substring(0, 120)}...`
                        : approval.reasoning}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => onApprove(approval.id)}
                        className="flex-1 rounded bg-emerald-700 px-3 py-1.5 font-mono text-[9px] uppercase text-white transition-colors hover:bg-emerald-600"
                        aria-label={`Approve action by ${approval.agentName}`}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => onDeny(approval.id)}
                        className="flex-1 rounded bg-red-800 px-3 py-1.5 font-mono text-[9px] uppercase text-white transition-colors hover:bg-red-700"
                        aria-label={`Deny action by ${approval.agentName}`}
                      >
                        Deny
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Chat */}
          <section aria-label="Chat" className="flex flex-col">
            <h2 className="pixel-text mb-3 text-[10px] uppercase tracking-wider text-slate-400">
              Chat
            </h2>
            <div className="retro-panel flex flex-col">
              <div
                className="max-h-64 overflow-y-auto px-3 py-2"
                role="log"
                aria-live="polite"
                aria-label="Chat messages"
              >
                {chatMessages.length === 0 ? (
                  <p className="py-4 text-center font-mono text-[9px] italic text-slate-600">
                    No messages yet
                  </p>
                ) : (
                  chatMessages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`py-0.5 font-mono text-[9px] ${
                        msg.isSystem
                          ? 'text-center italic text-slate-500'
                          : ''
                      }`}
                    >
                      {msg.isSystem ? (
                        <span>{msg.content}</span>
                      ) : (
                        <>
                          <span className="text-[8px] text-slate-600">
                            {formatHM(msg.timestamp)}
                          </span>{' '}
                          <span className="font-semibold text-emerald-400">
                            {msg.senderName}
                          </span>
                          {': '}
                          <span className="text-slate-300">{msg.content}</span>
                        </>
                      )}
                    </div>
                  ))
                )}
                <div ref={chatEndRef} />
              </div>

              <form
                onSubmit={handleChatSubmit}
                className="border-t border-slate-700 p-2"
              >
                <label htmlFor="simplified-chat-input" className="sr-only">
                  Chat message
                </label>
                <input
                  id="simplified-chat-input"
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Type a message..."
                  maxLength={500}
                  className="w-full rounded bg-slate-800 px-2 py-1 text-xs text-slate-200 placeholder-slate-500 outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </form>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
