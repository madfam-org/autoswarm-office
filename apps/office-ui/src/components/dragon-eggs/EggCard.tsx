'use client';

/**
 * One egg in the grid — visual + status + handle + days-since-laid.
 *
 * Click handler opens the EggDetail drawer (wired in
 * ``DragonEggsPage``). The card body is a ``<button>`` so keyboard
 * navigation works out of the box.
 *
 * Tone: playful but operator-grade. Status reads "hatching: day 4
 * of 7" — clear, actionable, no exclamation points or emoji.
 */

import {
  EGG_STATUS_LABELS,
  PLATFORM_LABELS,
  type Egg,
} from './types';
import { EggArt } from './EggArt';

interface EggCardProps {
  egg: Egg;
  onSelect: (egg: Egg) => void;
}

function daysSince(iso: string): number {
  if (!iso) return 0;
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.floor((now - then) / (24 * 60 * 60 * 1000));
}

function platformAccent(platform: Egg['platform']): string {
  // Operator-grade muted accents — not platform brand colors.
  switch (platform) {
    case 'mastodon':
      return 'border-l-solarpunk-wood';
    case 'bluesky':
      return 'border-l-solarpunk-glass';
    case 'reddit':
      return 'border-l-solarpunk-solar';
  }
}

export function EggCard({ egg, onSelect }: EggCardProps) {
  const days = daysSince(egg.laid_at);
  const stageLabel = EGG_STATUS_LABELS[egg.status];
  const stageDetail =
    egg.status === 'matured'
      ? 'Autonomous tier'
      : egg.status === 'hatched'
      ? 'First promo posted'
      : `Day ${Math.min(days + 1, 7)} of 7`;

  const progressPct = Math.round(egg.progress * 100);

  return (
    <button
      type="button"
      onClick={() => onSelect(egg)}
      className={`group flex w-full flex-col items-stretch gap-3 rounded-md border-l-4 ${platformAccent(
        egg.platform,
      )} border border-slate-800 bg-slate-900/60 p-4 text-left transition hover:border-slate-700 hover:bg-slate-900/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar`}
      aria-label={`${egg.display_name} — ${stageLabel}, ${progressPct}% progress`}
      data-testid={`egg-card-${egg.id}`}
    >
      <div className="flex items-start gap-4">
        <EggArt status={egg.status} platform={egg.platform} size={72} />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="truncate text-sm font-semibold text-slate-100" title={egg.display_name}>
            {egg.display_name}
          </h3>
          <p className="truncate text-xs text-slate-400" title={egg.handle}>
            {egg.handle}
          </p>
          <p className="text-xs text-slate-500">
            <span className="text-slate-400">{PLATFORM_LABELS[egg.platform]}</span>
            <span className="px-1 text-slate-700">·</span>
            <span>{stageLabel}</span>
            <span className="px-1 text-slate-700">·</span>
            <span>{stageDetail}</span>
          </p>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-slate-500">
          <span>Warmup progress</span>
          <span className="tabular-nums text-slate-300">{progressPct}%</span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progressPct}
          aria-label={`${egg.display_name} warmup progress`}
        >
          <div
            className="h-full bg-gradient-to-r from-solarpunk-moss to-solarpunk-solar transition-[width] duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>
    </button>
  );
}
