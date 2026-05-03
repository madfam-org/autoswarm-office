'use client';

import { useDemoMode } from '@/hooks/useDemoMode';

export function DemoBanner() {
  const { convertToReal, exitDemo } = useDemoMode();

  return (
    <div
      className="fixed inset-x-0 top-0 z-banner flex items-center justify-center gap-4 bg-gradient-to-r from-amber-900/90 via-indigo-900/90 to-amber-900/90 px-4 py-1.5 text-center font-mono text-[9px] text-white backdrop-blur-sm"
      role="status"
      aria-live="polite"
      aria-label="Demo mode active"
    >
      <span className="text-amber-300">DEMO MODE</span>
      <span className="text-slate-300">Actions are simulated</span>
      <button
        onClick={convertToReal}
        className="touch-target rounded bg-indigo-600 px-2 py-0.5 text-[8px] text-white transition-colors hover:bg-indigo-500"
      >
        Sign In for Real
      </button>
      <button
        onClick={exitDemo}
        className="touch-target rounded border border-slate-500 px-2 py-0.5 text-[8px] text-slate-300 transition-colors hover:bg-slate-700"
      >
        Exit
      </button>
    </div>
  );
}
