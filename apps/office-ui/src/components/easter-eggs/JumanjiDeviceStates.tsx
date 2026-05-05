'use client';

/**
 * Storybook-replacement showcase. Renders all four states side-by-side
 * with both light + dark backgrounds + reduced-motion mode so design
 * can iterate without running the full app or wiring Storybook.
 *
 * Mounted at `/jumanji/preview` (see app/jumanji/preview/page.tsx).
 * NOT linked from the rest of the UI — a known-URL preview only.
 */
import { JumanjiDeviceArt } from './JumanjiDeviceArt';
import type { JumanjiState } from './useJumanjiState';

const STATES: JumanjiState[] = ['resting', 'curious', 'awakened', 'portal'];

function Cell({
  state,
  reducedMotion,
  bg,
}: {
  state: JumanjiState;
  reducedMotion: boolean;
  bg: 'dark' | 'light';
}) {
  return (
    <div
      className={`flex flex-col items-center gap-3 rounded-md border p-6 ${
        bg === 'dark'
          ? 'border-slate-800 bg-slate-950 text-slate-300'
          : 'border-slate-300 bg-slate-100 text-slate-700'
      }`}
    >
      <div className="text-[10px] uppercase tracking-widest opacity-60">
        {state}
        {reducedMotion ? ' · reduced-motion' : ''}
      </div>
      <JumanjiDeviceArt state={state} reducedMotion={reducedMotion} tickFrame={3} />
      <div className="text-[10px] opacity-60">{bg} bg</div>
    </div>
  );
}

export function JumanjiDeviceStates() {
  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <h1 className="mb-6 text-lg text-emerald-300">Jumanji Device — All States</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {STATES.map((s) => (
          <Cell key={`d-${s}`} state={s} reducedMotion={false} bg="dark" />
        ))}
        {STATES.map((s) => (
          <Cell key={`l-${s}`} state={s} reducedMotion={false} bg="light" />
        ))}
        {STATES.map((s) => (
          <Cell key={`dr-${s}`} state={s} reducedMotion={true} bg="dark" />
        ))}
      </div>
    </div>
  );
}
