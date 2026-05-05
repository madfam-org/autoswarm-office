'use client';

/**
 * Drawer view: full egg detail with the action timeline.
 *
 * Operator can:
 *  - execute a planned/pending_human action (sets in_flight; worker
 *    picks it up on the next tick or admin marks it done by hand for
 *    HITL types)
 *  - skip an action (counts toward progress)
 *  - release the egg (force matured, or delete entirely)
 *
 * Actions render grouped by day_offset so the 7-day curve is readable.
 */

import { useEffect, useState } from 'react';

import { executeAction, getEgg, releaseEgg, skipAction } from './api';
import { EggArt } from './EggArt';
import {
  ACTION_STATUS_LABELS,
  ACTION_TYPE_LABELS,
  EGG_STATUS_LABELS,
  PLATFORM_LABELS,
  type ActionStatus,
  type EggDetail as EggDetailT,
  type WarmupAction,
} from './types';

interface EggDetailProps {
  eggId: string;
  onClose: () => void;
  onChanged: () => void;
}

const ACTION_STATUS_COLORS: Record<ActionStatus, string> = {
  planned: 'text-slate-400',
  pending_human: 'text-solarpunk-solar',
  in_flight: 'text-solarpunk-glass',
  completed: 'text-semantic-success-light',
  failed: 'text-semantic-error-light',
  skipped: 'text-slate-500',
};

export function EggDetail({ eggId, onClose, onChanged }: EggDetailProps) {
  const [egg, setEgg] = useState<EggDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setError(null);
    try {
      const fresh = await getEgg(eggId);
      setEgg(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load egg');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eggId]);

  async function onExecute(action: WarmupAction) {
    try {
      await executeAction(eggId, action.id);
      await refresh();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to execute action');
    }
  }

  async function onSkip(action: WarmupAction) {
    try {
      await skipAction(eggId, action.id, 'Skipped from office UI');
      await refresh();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to skip action');
    }
  }

  async function onRelease() {
    if (!confirm('Release this egg? This deletes the warmup plan.')) return;
    try {
      await releaseEgg(eggId);
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to release egg');
    }
  }

  async function onForceMatured() {
    if (!confirm('Force this egg to matured? This skips the warmup curve.')) return;
    try {
      await releaseEgg(eggId, 'matured');
      await refresh();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to force matured');
    }
  }

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 w-full max-w-xl overflow-y-auto border-l border-slate-800 bg-slate-950 shadow-2xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="egg-detail-title"
    >
      <header className="flex items-start gap-3 border-b border-slate-800 p-5">
        {egg && <EggArt status={egg.status} platform={egg.platform} size={64} />}
        <div className="min-w-0 flex-1">
          <h2 id="egg-detail-title" className="truncate text-base font-semibold text-slate-100">
            {egg?.display_name ?? 'Egg'}
          </h2>
          {egg && (
            <p className="text-xs text-slate-400">
              {PLATFORM_LABELS[egg.platform]} · {EGG_STATUS_LABELS[egg.status]} ·{' '}
              {Math.round(egg.progress * 100)}% complete
            </p>
          )}
          {egg?.handle && <p className="mt-1 truncate text-xs text-slate-500">{egg.handle}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
        >
          {/* close icon — pure SVG, no emoji */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3 L13 13 M13 3 L3 13" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      <div className="space-y-4 p-5">
        {loading && <p className="text-sm text-slate-400">Loading egg…</p>}
        {error && (
          <p className="rounded-md border border-semantic-error/40 bg-semantic-error-dark/20 px-3 py-2 text-xs text-semantic-error-light" role="alert">
            {error}
          </p>
        )}
        {egg && <ActionTimeline egg={egg} onExecute={onExecute} onSkip={onSkip} />}
        {egg && (
          <div className="space-y-2 border-t border-slate-800 pt-4">
            <h3 className="text-xs font-medium uppercase tracking-wider text-slate-400">Admin</h3>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onForceMatured}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
              >
                Force matured
              </button>
              <button
                type="button"
                onClick={onRelease}
                className="rounded-md border border-semantic-error/40 px-3 py-1.5 text-xs text-semantic-error-light hover:bg-semantic-error-dark/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-semantic-error"
              >
                Release egg
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

interface ActionTimelineProps {
  egg: EggDetailT;
  onExecute: (a: WarmupAction) => void;
  onSkip: (a: WarmupAction) => void;
}

function ActionTimeline({ egg, onExecute, onSkip }: ActionTimelineProps) {
  const grouped = new Map<number, WarmupAction[]>();
  for (const a of egg.actions) {
    const arr = grouped.get(a.day_offset) ?? [];
    arr.push(a);
    grouped.set(a.day_offset, arr);
  }
  const days = [...grouped.keys()].sort((a, b) => a - b);

  return (
    <div className="space-y-4">
      <h3 className="text-xs font-medium uppercase tracking-wider text-slate-400">
        Warmup timeline
      </h3>
      {days.map((day) => (
        <section key={day} className="space-y-2">
          <header className="flex items-baseline gap-2">
            <h4 className="text-sm font-medium text-slate-200">Day {day}</h4>
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              {grouped.get(day)?.length ?? 0} action{(grouped.get(day)?.length ?? 0) === 1 ? '' : 's'}
            </span>
          </header>
          <ul className="space-y-2">
            {grouped.get(day)?.map((action) => (
              <li
                key={action.id}
                className="rounded-md border border-slate-800 bg-slate-900/40 p-3"
                data-testid={`action-row-${action.id}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-slate-200">
                      {ACTION_TYPE_LABELS[action.action_type]}
                    </p>
                    {action.notes && (
                      <p className="mt-1 text-xs text-slate-500">{action.notes}</p>
                    )}
                  </div>
                  <span
                    className={`shrink-0 text-[10px] font-medium uppercase tracking-wider ${ACTION_STATUS_COLORS[action.status]}`}
                  >
                    {ACTION_STATUS_LABELS[action.status]}
                  </span>
                </div>
                {action.status !== 'completed' && action.status !== 'skipped' && (
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={() => onExecute(action)}
                      className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 hover:border-slate-600"
                    >
                      Execute now
                    </button>
                    <button
                      type="button"
                      onClick={() => onSkip(action)}
                      className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:border-slate-600"
                    >
                      Skip
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
