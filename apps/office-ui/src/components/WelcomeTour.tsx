'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * First-run welcome tour (Gather v2 design brief surface #3). A short
 * step sequence that orients a new arrival: what this place is, that the
 * agents are real teammates, how to put one to work, and how to keep an
 * eye on things. Left-rail step card with a progress bar + Next, matching
 * the Gather reference.
 *
 * Shown once (persisted). Never blocks the office — it's a dismissable
 * overlay card, not a modal gate. Skipped in demo? No — the demo is
 * exactly where a first-timer benefits most, so it runs there too.
 */

const SEEN_KEY = 'selva:welcome-tour-seen';

export function hasSeenWelcomeTour(): boolean {
  try {
    if (typeof localStorage === 'undefined' || typeof localStorage.getItem !== 'function') {
      return false;
    }
    return localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

interface TourStep {
  title: string;
  body: string;
  /** Optional emoji glyph for the step. */
  glyph: string;
}

const STEPS: TourStep[] = [
  {
    glyph: '🌿',
    title: 'Welcome to your Selva office',
    body: "This is a living office where AI agents work alongside you — coding, researching, filing, deploying. Everything they do is under your control.",
  },
  {
    glyph: '🤖',
    title: 'Your agents are teammates',
    body: 'See them on the roster to the left, each with a role and a live status. When one is working you’ll watch it move and act, not just spin a hidden job.',
  },
  {
    glyph: '⚡',
    title: 'Put an agent to work',
    body: 'Open Dispatch (the + New Task control) to hand off a task. You approve anything consequential before it happens — no black boxes.',
  },
  {
    glyph: '👁️',
    title: 'Stay in the loop',
    body: 'The approval queue flags anything waiting on you, and the usage meter up top shows your plan’s daily compute. That’s it — dispatch something and watch it come to life.',
  },
];

interface WelcomeTourProps {
  /** Render nothing when false (caller gates on first-visit). */
  open: boolean;
  onClose: () => void;
  /** Offset right so the card clears the open space-roster rail (md+). */
  rosterOpen?: boolean;
}

export function WelcomeTour({ open, onClose, rosterOpen = false }: WelcomeTourProps) {
  const [step, setStep] = useState(0);

  const finish = useCallback(() => {
    try {
      if (typeof localStorage !== 'undefined' && typeof localStorage.setItem === 'function') {
        localStorage.setItem(SEEN_KEY, '1');
      }
    } catch {
      /* best-effort */
    }
    onClose();
  }, [onClose]);

  // Esc dismisses.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, finish]);

  if (!open) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;
  const progress = ((step + 1) / STEPS.length) * 100;

  return (
    <div
      className={`pointer-events-auto fixed top-20 z-modal w-[20rem] max-w-[calc(100vw-2rem)] rounded-2xl border border-edge bg-surface-raised p-5 shadow-lg animate-fade-in ${
        rosterOpen ? 'left-4 md:left-[17rem]' : 'left-4'
      }`}
      role="dialog"
      aria-modal="false"
      aria-labelledby="welcome-tour-title"
    >
      {/* Progress */}
      <div className="mb-4 h-1 w-full overflow-hidden rounded-full bg-surface-overlay">
        <div
          className="h-full rounded-full bg-accent transition-all duration-300"
          style={{ width: `${progress}%` }}
          role="progressbar"
          aria-valuenow={step + 1}
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
        />
      </div>

      <div className="mb-1 flex items-center justify-between">
        <span className="text-2xl" aria-hidden>
          {current.glyph}
        </span>
        <button
          type="button"
          onClick={finish}
          className="rounded p-1 text-xs text-ink-muted hover:text-ink"
          aria-label="Skip tour"
        >
          Skip
        </button>
      </div>

      <h2 id="welcome-tour-title" className="mb-1.5 text-base font-semibold text-ink">
        {current.title}
      </h2>
      <p className="mb-5 text-sm leading-relaxed text-ink-muted">{current.body}</p>

      <div className="flex items-center justify-between">
        <span className="text-xs text-ink-muted">
          {step + 1} of {STEPS.length}
        </span>
        <button
          type="button"
          onClick={() => (isLast ? finish() : setStep((s) => s + 1))}
          className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90"
        >
          {isLast ? 'Get started' : 'Next'}
        </button>
      </div>
    </div>
  );
}
