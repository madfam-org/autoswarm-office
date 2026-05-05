'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Jumanji easter egg state machine.
 *
 * resting   -> the device is dormant. faint glyphs, easy to miss.
 * curious   -> first interaction (focus / hover-5s / first key of sequence).
 *              glyphs glow. dice begins to rumble.
 * awakened  -> sequence partially complete. dice is rolling, viewport
 *              cycles symbols.
 * portal    -> sequence complete. "Step in" CTA visible.
 *
 * The activation sequence is a typed J-U-M-A-N-J-I when the device
 * has keyboard focus. The keyboard sequence is the chosen path
 * because:
 *   1) it's accessible (every WCAG-conformant device has a keyboard
 *      surface, including switch users),
 *   2) it can't be triggered by accident,
 *   3) it feels game-like — typing a magic word is a gesture from the
 *      *Heaven's Vault* / *Disco Elysium* lineage,
 *   4) it documents itself — a curious user who hovers will see the
 *      "type the word" hint after 1.5s.
 *
 * As a pointer-only fallback (touch devices, motor-impaired users who
 * can't type fast enough), three taps within 2.5s while the device is
 * already in `curious` state will also advance to `portal`.
 */

export type JumanjiState = 'resting' | 'curious' | 'awakened' | 'portal';

const STORAGE_KEY = 'jumanji_discovered';
const RESET_QUERY_PARAM = 'reset_jumanji';
const SEQUENCE = 'JUMANJI';
const SEQUENCE_TIMEOUT_MS = 4000;
const TAP_FALLBACK_COUNT = 3;
const TAP_FALLBACK_WINDOW_MS = 2500;
const HOVER_AWAKEN_MS = 1500;

export interface UseJumanjiStateResult {
  state: JumanjiState;
  /** How many letters of the sequence are matched. */
  progress: number;
  /** Whether the user has seen this device before (drives "curious by default"). */
  discovered: boolean;
  /** Whether the user prefers reduced motion. */
  reducedMotion: boolean;
  /** Pointer-enter handler. */
  onPointerEnter: () => void;
  /** Pointer-leave handler. */
  onPointerLeave: () => void;
  /** Focus handler. */
  onFocus: () => void;
  /** Blur handler. */
  onBlur: () => void;
  /** Click / Enter / Space handler. */
  onActivate: () => void;
  /** Keyboard handler — must be wired to the device's onKeyDown. */
  onKeyDown: (e: React.KeyboardEvent) => void;
  /** Reset to resting (used after closing the portal). */
  reset: () => void;
}

function readDiscovered(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get(RESET_QUERY_PARAM) === '1') {
      window.localStorage.removeItem(STORAGE_KEY);
      return false;
    }
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function writeDiscovered(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, 'true');
  } catch {
    // Private mode / quota — silently ignore.
  }
}

function readReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function useJumanjiState(): UseJumanjiStateResult {
  const [discovered, setDiscovered] = useState<boolean>(false);
  const [state, setState] = useState<JumanjiState>('resting');
  const [progress, setProgress] = useState<number>(0);
  const [reducedMotion, setReducedMotion] = useState<boolean>(false);

  const sequenceRef = useRef<string>('');
  const lastKeyTsRef = useRef<number>(0);
  const tapTimestampsRef = useRef<number[]>([]);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate from localStorage + matchMedia after mount (SSR-safe).
  useEffect(() => {
    const isDiscovered = readDiscovered();
    setDiscovered(isDiscovered);
    if (isDiscovered) setState('curious');
    setReducedMotion(readReducedMotion());

    const mql = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mql?.addEventListener?.('change', handler);
    return () => mql?.removeEventListener?.('change', handler);
  }, []);

  const advanceSequence = useCallback(
    (newProgress: number) => {
      setProgress(newProgress);
      if (newProgress === 0) {
        setState(discovered ? 'curious' : 'resting');
        return;
      }
      if (newProgress >= SEQUENCE.length) {
        setState('portal');
        if (!discovered) {
          writeDiscovered();
          setDiscovered(true);
        }
        return;
      }
      // 1 letter -> curious, 3+ letters -> awakened.
      setState(newProgress >= 3 ? 'awakened' : 'curious');
    },
    [discovered],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Enter / Space behave as activate (handled by onActivate via onClick).
      if (e.key === 'Enter' || e.key === ' ') return;

      const now = Date.now();
      // Reset sequence if the user pauses too long.
      if (now - lastKeyTsRef.current > SEQUENCE_TIMEOUT_MS) {
        sequenceRef.current = '';
      }
      lastKeyTsRef.current = now;

      const upper = e.key.toUpperCase();
      if (upper.length !== 1 || !/[A-Z]/.test(upper)) return;

      const expected = SEQUENCE[sequenceRef.current.length];
      if (upper === expected) {
        sequenceRef.current += upper;
        advanceSequence(sequenceRef.current.length);
        e.preventDefault();
      } else {
        // Mismatch — reset, but if the wrong key happens to be the first
        // letter of the sequence, count it.
        sequenceRef.current = upper === SEQUENCE[0] ? SEQUENCE[0] : '';
        advanceSequence(sequenceRef.current.length);
      }
    },
    [advanceSequence],
  );

  const onActivate = useCallback(() => {
    // Pointer-only fallback: 3 taps within 2.5s while curious -> portal.
    const now = Date.now();
    tapTimestampsRef.current = [
      ...tapTimestampsRef.current.filter((t) => now - t < TAP_FALLBACK_WINDOW_MS),
      now,
    ];

    if (state === 'resting') {
      setState('curious');
      return;
    }

    if (tapTimestampsRef.current.length >= TAP_FALLBACK_COUNT) {
      setState('portal');
      if (!discovered) {
        writeDiscovered();
        setDiscovered(true);
      }
      tapTimestampsRef.current = [];
      return;
    }

    // Otherwise nudge through awakened.
    if (state === 'curious') setState('awakened');
  }, [state, discovered]);

  const onPointerEnter = useCallback(() => {
    if (state !== 'resting') return;
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setState((prev) => (prev === 'resting' ? 'curious' : prev));
    }, HOVER_AWAKEN_MS);
  }, [state]);

  const onPointerLeave = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  }, []);

  const onFocus = useCallback(() => {
    setState((prev) => (prev === 'resting' ? 'curious' : prev));
  }, []);

  const onBlur = useCallback(() => {
    // Don't reset state on blur — the user might be tabbing to the modal.
  }, []);

  const reset = useCallback(() => {
    sequenceRef.current = '';
    tapTimestampsRef.current = [];
    setProgress(0);
    setState(discovered ? 'curious' : 'resting');
  }, [discovered]);

  return {
    state,
    progress,
    discovered,
    reducedMotion,
    onPointerEnter,
    onPointerLeave,
    onFocus,
    onBlur,
    onActivate,
    onKeyDown,
    reset,
  };
}

export const JUMANJI_TEST_HOOKS = {
  STORAGE_KEY,
  SEQUENCE,
  SEQUENCE_TIMEOUT_MS,
  RESET_QUERY_PARAM,
} as const;
