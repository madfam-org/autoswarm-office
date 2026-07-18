'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

/**
 * Tropical solarpunk day/night theming.
 *
 * Modes:
 *  - 'auto'  — follows the local clock (day 07:00–18:59, night otherwise),
 *              re-evaluated every minute so dawn/dusk flips live.
 *  - 'day' / 'night' — explicit operator override, persisted.
 *
 * The resolved theme lands on <html data-theme="…">, which drives the
 * CSS-variable palettes in globals.css. A matching inline script in the
 * root layout sets the attribute pre-hydration to avoid a theme flash.
 */

export type ThemeMode = 'auto' | 'day' | 'night';
export type ResolvedTheme = 'day' | 'night';

const STORAGE_KEY = 'selva:theme-mode';
const DAY_START_HOUR = 7;
const NIGHT_START_HOUR = 19;

export function resolveByClock(date: Date = new Date()): ResolvedTheme {
  const h = date.getHours();
  return h >= DAY_START_HOUR && h < NIGHT_START_HOUR ? 'day' : 'night';
}

function readStoredMode(): ThemeMode {
  try {
    // Guard the METHOD, not just the global — some runtimes expose a
    // localStorage object without getItem.
    if (
      typeof localStorage === 'undefined' ||
      typeof localStorage.getItem !== 'function'
    ) {
      return 'auto';
    }
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === 'day' || raw === 'night' || raw === 'auto' ? raw : 'auto';
  } catch {
    return 'auto';
  }
}

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: 'auto',
  resolved: 'night',
  setMode: () => undefined,
});

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>('auto');
  const [resolved, setResolved] = useState<ResolvedTheme>('night');

  // Initial read happens client-side only (SSR renders the default and the
  // layout's inline script has already stamped the attribute).
  useEffect(() => {
    const stored = readStoredMode();
    setModeState(stored);
    setResolved(stored === 'auto' ? resolveByClock() : stored);
  }, []);

  // Auto mode follows the sun (well, the clock).
  useEffect(() => {
    if (mode !== 'auto') return;
    const tick = () => setResolved(resolveByClock());
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, [mode]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolved);
  }, [resolved]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    setResolved(next === 'auto' ? resolveByClock() : next);
    try {
      if (
        typeof localStorage !== 'undefined' &&
        typeof localStorage.setItem === 'function'
      ) {
        localStorage.setItem(STORAGE_KEY, next);
      }
    } catch {
      /* storage unavailable — override lives for the session only */
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * Inline pre-hydration script body — stamped into the root layout <head>
 * so first paint already has the right palette. Mirrors readStoredMode +
 * resolveByClock; keep the three in sync.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var m='auto';try{if(typeof localStorage!=='undefined'&&typeof localStorage.getItem==='function'){var r=localStorage.getItem('${STORAGE_KEY}');if(r==='day'||r==='night'||r==='auto')m=r;}}catch(e){}var h=new Date().getHours();var t=m==='auto'?(h>=${DAY_START_HOUR}&&h<${NIGHT_START_HOUR}?'day':'night'):m;document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','night');}})();`;
