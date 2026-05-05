'use client';

/**
 * Visual grid of all eggs. Empty state, loading state, and per-card
 * click → drawer.
 */

import type { Egg } from './types';
import { EggCard } from './EggCard';

interface EggGridProps {
  eggs: Egg[];
  loading?: boolean;
  error?: string | null;
  onSelect: (egg: Egg) => void;
  onLayFirst: () => void;
}

export function EggGrid({ eggs, loading, error, onSelect, onLayFirst }: EggGridProps) {
  if (loading) {
    return (
      <div
        className="rounded-md border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-400"
        role="status"
        aria-live="polite"
      >
        Loading eggs…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-semantic-error/40 bg-semantic-error-dark/20 p-6 text-sm text-semantic-error-light"
        role="alert"
      >
        {error}
      </div>
    );
  }

  if (eggs.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-700 bg-slate-900/30 p-12 text-center">
        <h2 className="text-base font-semibold text-slate-200">
          No dragons yet
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          Lay your first egg to start the 7-day warmup.
        </p>
        <button
          type="button"
          onClick={onLayFirst}
          className="mt-6 inline-flex items-center justify-center rounded-md border border-solarpunk-solar/60 bg-solarpunk-solar/10 px-4 py-2 text-sm font-medium text-solarpunk-solar transition hover:bg-solarpunk-solar/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
        >
          Lay an egg
        </button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {eggs.map((egg) => (
        <EggCard key={egg.id} egg={egg} onSelect={onSelect} />
      ))}
    </div>
  );
}
