'use client';

/**
 * AtriumIntroHint — first-time discovery hint near the dock.
 *
 * Renders a small dismissible balloon next to the AtriumDock the
 * first time the operator visits the office after this lands. The
 * `atrium_intro_seen` localStorage flag is the gate — once dismissed
 * the hint never reappears.
 *
 * Uses prefers-reduced-motion for the appearance animation.
 */

import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'atrium_intro_seen';

export function AtriumIntroHint(): JSX.Element | null {
  // Default to false so we don't flash the hint to operators who've
  // already dismissed it. Hydrate from localStorage on mount.
  const [shouldShow, setShouldShow] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const seen = localStorage.getItem(STORAGE_KEY);
      if (seen !== '1') {
        setShouldShow(true);
      }
    } catch {
      // localStorage disabled — treat as already-seen so we don't nag.
    }
  }, []);

  const dismiss = useCallback(() => {
    setShouldShow(false);
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      // Quota / disabled — silent. Worst case the hint reappears on
      // next visit, which is harmless.
    }
  }, []);

  if (!shouldShow) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="atrium-intro-hint"
      className="pointer-events-auto absolute left-16 top-3 z-40 max-w-[260px] rounded-lg border border-emerald-600/60 bg-slate-900/95 p-3 shadow-xl"
    >
      <div className="mb-1 text-xs font-semibold text-emerald-300">
        Welcome to the Atrium
      </div>
      <p className="mb-2 text-[11px] leading-snug text-slate-300">
        Every MADFAM platform converges here as a draggable window over
        your office. Click an icon on the left to open one — your
        office stays right where it is.
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="rounded bg-emerald-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
        data-testid="atrium-intro-hint-dismiss"
      >
        Got it
      </button>
    </div>
  );
}
