'use client';

import { useState, useEffect, type FC } from 'react';
import type { MeetingNotes, MeetingNotesStatus } from '@/hooks/useMeetingNotes';
import { useFocusTrap } from '@/hooks/useFocusTrap';

interface MeetingNotesPanelProps {
  open: boolean;
  onClose: () => void;
  status: MeetingNotesStatus;
  notes: MeetingNotes | null;
  error: string | null;
}

export const MeetingNotesPanel: FC<MeetingNotesPanelProps> = ({
  open,
  onClose,
  status,
  notes,
  error,
}) => {
  const [visible, setVisible] = useState(false);
  const [transcriptExpanded, setTranscriptExpanded] = useState(false);
  const [checkedItems, setCheckedItems] = useState<Set<number>>(new Set());

  // Slide animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      setTranscriptExpanded(false);
      setCheckedItems(new Set());
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

  const toggleItem = (index: number) => {
    setCheckedItems((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const focusTrapRef = useFocusTrap<HTMLElement>(open);

  if (!open) return null;

  return (
    <aside
      ref={focusTrapRef}
      className={`fixed right-0 top-0 z-modal h-full w-full max-w-96 transform transition-transform duration-300 sm:w-96 ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-labelledby="meeting-notes-title"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex h-full flex-col bg-slate-900/95 backdrop-blur-sm pixel-border-accent">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <h2 id="meeting-notes-title" className="pixel-text text-[10px] uppercase tracking-wider text-indigo-400">
            Meeting Notes
          </h2>
          <button
            onClick={onClose}
            className="touch-target rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            aria-label="Close meeting notes"
          >
            ESC
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Loading states */}
          {(status === 'dispatching' || status === 'processing') && (
            <div className="flex flex-col items-center justify-center py-8 space-y-3">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
              <p className="font-mono text-[10px] text-slate-400">
                {status === 'dispatching' ? 'Dispatching task...' : 'Generating meeting notes...'}
              </p>
              <p className="font-mono text-[8px] text-slate-600">
                This may take a few minutes
              </p>
            </div>
          )}

          {/* Error */}
          {status === 'error' && error && (
            <div className="rounded bg-red-900/30 border border-red-800 px-3 py-2">
              <p className="font-mono text-[9px] text-red-400">{error}</p>
            </div>
          )}

          {/* Notes content */}
          {status === 'completed' && notes && (
            <>
              {/* Summary */}
              <section>
                <h3 className="font-mono text-[8px] uppercase text-slate-500 mb-2">
                  Summary
                </h3>
                <div className="rounded bg-slate-800/60 border border-slate-700 px-3 py-2">
                  <p className="font-mono text-[9px] text-slate-300 whitespace-pre-wrap leading-relaxed">
                    {notes.summary}
                  </p>
                </div>
              </section>

              {/* Action Items */}
              <section>
                <h3 className="font-mono text-[8px] uppercase text-slate-500 mb-2">
                  Action Items ({notes.action_items.length})
                </h3>
                {notes.action_items.length === 0 ? (
                  <p className="font-mono text-[9px] text-slate-600 italic">
                    No action items extracted
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {notes.action_items.map((item, idx) => (
                      <li
                        key={idx}
                        className="flex items-start gap-2 rounded bg-slate-800/40 border border-slate-700/50 px-2 py-1.5"
                      >
                        <input
                          type="checkbox"
                          checked={checkedItems.has(idx)}
                          onChange={() => toggleItem(idx)}
                          className="mt-0.5 accent-indigo-500 shrink-0"
                          aria-label={`Mark "${item.task}" as done`}
                        />
                        <div className="flex-1 min-w-0">
                          <p
                            className={`font-mono text-[9px] ${
                              checkedItems.has(idx) ? 'text-slate-600 line-through' : 'text-slate-300'
                            }`}
                          >
                            {item.task}
                          </p>
                          <div className="flex gap-3 mt-0.5">
                            {item.assignee && (
                              <span className="font-mono text-[7px] text-cyan-500">
                                {item.assignee}
                              </span>
                            )}
                            {item.deadline && (
                              <span className="font-mono text-[7px] text-amber-500">
                                {item.deadline}
                              </span>
                            )}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Transcript (expandable) */}
              <section>
                <button
                  onClick={() => setTranscriptExpanded((prev) => !prev)}
                  className="flex items-center gap-1 font-mono text-[8px] uppercase text-slate-500 hover:text-slate-300"
                >
                  <span>{transcriptExpanded ? '-' : '+'}</span>
                  Full Transcript
                </button>
                {transcriptExpanded && (
                  <div className="mt-2 rounded bg-slate-800/40 border border-slate-700/50 px-3 py-2 max-h-64 overflow-y-auto">
                    <p className="font-mono text-[8px] text-slate-400 whitespace-pre-wrap leading-relaxed">
                      {notes.transcript || 'No transcript available'}
                    </p>
                  </div>
                )}
              </section>
            </>
          )}

          {/* Idle state */}
          {status === 'idle' && (
            <div className="flex flex-col items-center justify-center py-8">
              <p className="font-mono text-[10px] text-slate-500">
                No meeting notes generated yet
              </p>
              <p className="font-mono text-[8px] text-slate-600 mt-1">
                Record a meeting and click &quot;Notes&quot; to generate
              </p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
