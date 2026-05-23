'use client';

import { useState, useEffect, useCallback, useMemo, type FC } from 'react';
import { CloseButton } from '@autoswarm/ui';
import type { ApprovalRequest, ActionCategory } from '@autoswarm/shared-types';
import { gameEventBus } from '@/game/PhaserGame';
import { EVENT_CHAT_FOCUS } from '@/lib/constants';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';
import { DiffViewer } from './DiffViewer';
import { PricingProposalDetails } from './PricingProposalDetails';
import { extractAffectedFiles, splitDiffByFile } from '@/lib/diffPaths';
import { timeAgo } from '@/lib/format-time';

const ACTION_TAGS: Record<ActionCategory, string> = {
  file_read: '[R]',
  file_write: '[W]',
  bash_execute: '[>]',
  git_commit: '[C]',
  git_push: '[P]',
  email_send: '[@]',
  crm_update: '[CRM]',
  deploy: '[D]',
  api_call: '[API]',
  pricing_proposal: '[$]',
};

const URGENCY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const URGENCY_STYLES: Record<string, string> = {
  low: 'text-slate-400 bg-slate-800',
  medium: 'text-amber-300 bg-amber-900/40',
  high: 'text-orange-300 bg-orange-900/40',
  critical: 'text-red-300 bg-red-900/40 animate-pulse',
};

interface ApprovalPanelProps {
  open: boolean;
  onClose: () => void;
  pendingApprovals: ApprovalRequest[];
  onApprove: (requestId: string, feedback?: string) => Promise<boolean>;
  onDeny: (requestId: string, feedback?: string) => Promise<boolean>;
  connected: boolean;
}

export const ApprovalPanel: FC<ApprovalPanelProps> = ({
  open,
  onClose,
  pendingApprovals,
  onApprove,
  onDeny,
  connected,
}) => {
  const [visible, setVisible] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [feedbackMap, setFeedbackMap] = useState<Record<string, string>>({});
  const [selectedFileIdx, setSelectedFileIdx] = useState<Record<string, number>>({});
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

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  // Suppress game input while textarea focused
  const handleFocus = useCallback(() => {
    gameEventBus.emit(EVENT_CHAT_FOCUS, true);
  }, []);
  const handleBlur = useCallback(() => {
    gameEventBus.emit(EVENT_CHAT_FOCUS, false);
  }, []);

  const handleApprove = useCallback(
    async (request: ApprovalRequest) => {
      const feedback = feedbackMap[request.id];
      const ok = await onApprove(request.id, feedback || undefined);
      addToast(
        ok ? `Approved: ${request.agentName}` : `Approval failed for ${request.agentName} — try again`,
        ok ? 'success' : 'error',
      );
      if (ok) {
        setFeedbackMap((prev) => {
          const next = { ...prev };
          delete next[request.id];
          return next;
        });
      }
    },
    [feedbackMap, onApprove, addToast],
  );

  const handleDeny = useCallback(
    async (request: ApprovalRequest) => {
      const feedback = feedbackMap[request.id];
      const ok = await onDeny(request.id, feedback || undefined);
      addToast(
        ok ? `Denied: ${request.agentName}` : `Deny failed for ${request.agentName} — try again`,
        ok ? 'warning' : 'error',
      );
      if (ok) {
        setFeedbackMap((prev) => {
          const next = { ...prev };
          delete next[request.id];
          return next;
        });
      }
    },
    [feedbackMap, onDeny, addToast],
  );

  // Memoised so typing in the feedback textarea (which causes ApprovalPanel to
  // re-render on every keystroke via setFeedbackMap) does not re-sort the
  // approvals array. Recomputes only when pendingApprovals changes.
  const sortedApprovals = useMemo(
    () =>
      [...pendingApprovals].sort((a, b) => {
        const urgencyDiff =
          (URGENCY_ORDER[a.urgency] ?? 3) - (URGENCY_ORDER[b.urgency] ?? 3);
        if (urgencyDiff !== 0) return urgencyDiff;
        return new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();
      }),
    [pendingApprovals],
  );

  if (!open) return null;

  return (
    <aside
      ref={trapRef}
      className={`fixed right-0 top-0 z-modal h-full w-full max-w-96 transform transition-transform duration-300 sm:w-96 ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-label="Approval queue panel"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex h-full flex-col bg-slate-900/95 backdrop-blur-sm pixel-border-accent">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <div className="flex items-center gap-2">
            <h2 className="pixel-text text-[10px] uppercase tracking-wider text-indigo-400">
              Approval Queue
            </h2>
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                connected ? 'bg-emerald-400' : 'bg-red-500 animate-pulse'
              }`}
              aria-label={connected ? 'Connected' : 'Disconnected'}
            />
          </div>
          <CloseButton onClick={onClose} label="Close approval panel" shortcut="ESC" />
        </div>

        {/* Content */}
        {sortedApprovals.length === 0 ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="font-mono text-[10px] italic text-slate-600">
              No pending approvals
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
            {sortedApprovals.map((request, idx) => {
              const isExpanded = expandedId === request.id;
              const feedback = feedbackMap[request.id] ?? '';
              const affectedFiles = extractAffectedFiles(request.diff);
              const diffSections = isExpanded ? splitDiffByFile(request.diff) : [];
              const activeFileIdx = Math.min(
                selectedFileIdx[request.id] ?? 0,
                Math.max(0, diffSections.length - 1),
              );
              return (
                <div
                  key={request.id}
                  className="retro-panel animate-fade-in-up"
                  style={{ animationDelay: `${idx * 30}ms` }}
                >
                  {/* Collapsed header - click to expand */}
                  <button
                    onClick={() =>
                      setExpandedId(isExpanded ? null : request.id)
                    }
                    className="w-full px-3 py-2 text-left"
                    aria-expanded={isExpanded}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono text-[9px] text-cyan-400 shrink-0">
                          {request.agentName}
                        </span>
                        <span className="font-mono text-[8px] text-slate-500 shrink-0">
                          {ACTION_TAGS[request.actionCategory] ??
                            `[${request.actionCategory}]`}
                        </span>
                        <span
                          className={`px-1.5 py-0.5 font-mono text-[7px] uppercase ${URGENCY_STYLES[request.urgency] ?? URGENCY_STYLES.low}`}
                        >
                          {request.urgency}
                        </span>
                      </div>
                      <span className="font-mono text-[7px] text-slate-600 shrink-0 ml-2">
                        {timeAgo(request.createdAt)}
                      </span>
                    </div>
                    {!isExpanded && (
                      <>
                        <p className="mt-1 font-mono text-[8px] text-slate-400 truncate">
                          {request.reasoning.substring(0, 80)}
                          {request.reasoning.length > 80 ? '...' : ''}
                        </p>
                        {affectedFiles.length > 0 && (
                          <div className="mt-1 flex items-center gap-1 flex-wrap">
                            <span className="font-mono text-[7px] uppercase text-slate-600">
                              Files:
                            </span>
                            {affectedFiles.slice(0, 2).map((f) => (
                              <span
                                key={`${f.kind}:${f.path}`}
                                className={`font-mono text-[7px] px-1 py-0.5 truncate max-w-[11rem] ${
                                  f.kind === 'added'
                                    ? 'bg-emerald-950/50 text-emerald-300'
                                    : f.kind === 'deleted'
                                    ? 'bg-red-950/50 text-red-300'
                                    : 'bg-indigo-950/50 text-indigo-300'
                                }`}
                                title={`${f.kind}: ${f.path}`}
                              >
                                {f.kind === 'added'
                                  ? '+ '
                                  : f.kind === 'deleted'
                                  ? '- '
                                  : '~ '}
                                {f.path}
                              </span>
                            ))}
                            {affectedFiles.length > 2 && (
                              <span className="font-mono text-[7px] text-slate-500">
                                +{affectedFiles.length - 2} more
                              </span>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="px-3 pb-3 space-y-2">
                      {request.actionCategory === 'pricing_proposal' ? (
                        <PricingProposalDetails request={request} />
                      ) : null}
                      <div className="border-l-2 border-indigo-500 bg-slate-800/50 p-3">
                        <p className="font-mono text-[9px] text-slate-300 whitespace-pre-wrap">
                          {request.reasoning}
                        </p>
                      </div>

                      {request.diff && diffSections.length > 1 && (
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="font-mono text-[7px] uppercase text-slate-500">
                            Jump to:
                          </span>
                          {diffSections.map((section, sIdx) => {
                            const isActive = sIdx === activeFileIdx;
                            const badgeClass =
                              section.kind === 'added'
                                ? 'bg-emerald-950/50 text-emerald-300'
                                : section.kind === 'deleted'
                                ? 'bg-red-950/50 text-red-300'
                                : 'bg-indigo-950/50 text-indigo-300';
                            const activeClass = isActive
                              ? 'ring-1 ring-indigo-400'
                              : 'opacity-60 hover:opacity-100';
                            return (
                              <button
                                key={`${section.kind}:${section.path}:${sIdx}`}
                                onClick={() =>
                                  setSelectedFileIdx((prev) => ({
                                    ...prev,
                                    [request.id]: sIdx,
                                  }))
                                }
                                className={`font-mono text-[7px] px-1 py-0.5 truncate max-w-[10rem] transition ${badgeClass} ${activeClass}`}
                                title={`${section.kind}: ${section.path}`}
                                aria-pressed={isActive}
                              >
                                {section.kind === 'added'
                                  ? '+ '
                                  : section.kind === 'deleted'
                                  ? '- '
                                  : '~ '}
                                {section.path}
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {request.diff && diffSections.length > 0 && (
                        <div className="max-h-48 overflow-auto">
                          <DiffViewer
                            diff={diffSections[activeFileIdx]?.body ?? request.diff}
                            ariaLabel={`Proposed diff for ${request.agentName}`}
                          />
                        </div>
                      )}

                      {request.diff && diffSections.length === 0 && (
                        <div className="max-h-48 overflow-auto">
                          <DiffViewer
                            diff={request.diff}
                            ariaLabel={`Proposed diff for ${request.agentName}`}
                          />
                        </div>
                      )}

                      <textarea
                        value={feedback}
                        onChange={(e) =>
                          setFeedbackMap((prev) => ({
                            ...prev,
                            [request.id]: e.target.value,
                          }))
                        }
                        onFocus={handleFocus}
                        onBlur={handleBlur}
                        placeholder="Feedback (optional)..."
                        rows={2}
                        className="w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 font-mono text-[9px] text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none resize-none"
                      />
                    </div>
                  )}

                  {/* Approve / Deny buttons - always visible */}
                  <div className="flex gap-2 px-3 pb-2">
                    <button
                      onClick={() => handleApprove(request)}
                      className="flex-1 rounded bg-emerald-700 px-3 py-1.5 font-mono text-[9px] uppercase text-white transition-colors hover:bg-emerald-600"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleDeny(request)}
                      className="flex-1 rounded bg-red-800 px-3 py-1.5 font-mono text-[9px] uppercase text-white transition-colors hover:bg-red-700"
                    >
                      Deny
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
};
