/**
 * Atrium window manager — Zustand store.
 *
 * Single source of truth for the floating-window overlay that powers
 * the MADFAM Ecosystem Atrium inside the Selva office. The store
 * tracks every window opened during the session; closing a window
 * REMOVES it (which unmounts the iframe), minimizing keeps the iframe
 * mounted but visually collapsed.
 *
 * Critical invariant for iframe state preservation: as long as a
 * window is in the `windows` map, its DOM node stays mounted in the
 * React tree. Focus changes only re-stack via z-index — they MUST NOT
 * remount the iframe. Remounting blows away login state, scroll
 * position, form fields, etc., which is the whole point of mounting
 * the iframe ONCE on first open per the spec.
 *
 * Per-slug position+size persists to localStorage under
 * `atrium:layout:<slug>` so windows reopen where the operator last
 * left them.
 */

import { create } from 'zustand';

export type WindowState = 'windowed' | 'minimized' | 'maximized';

export type LaunchVariant = 'app' | 'admin' | 'public';

export interface WindowGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AtriumWindow {
  /** Catalog slug — also serves as the window id (one window per slug). */
  slug: string;
  /** Resolved iframe URL at the moment of open. */
  url: string;
  /** Display name (cached from catalog at open time). */
  title: string;
  /** Which variant of the platform was launched (admin pill in chrome). */
  variant: LaunchVariant;
  state: WindowState;
  geometry: WindowGeometry;
  /** Pre-maximize geometry, restored on un-maximize. */
  prevGeometry?: WindowGeometry;
  /** Stacking order — higher z is rendered later. */
  zIndex: number;
  /** Monotonic open timestamp; tie-breaker for default focus. */
  openedAt: number;
}

interface AtriumStore {
  windows: Record<string, AtriumWindow>;
  /** Slug of the currently focused window, or null when none open. */
  focusedSlug: string | null;
  /** Monotonic counter for z-index assignment. */
  zCounter: number;

  open: (input: {
    slug: string;
    url: string;
    title: string;
    variant?: LaunchVariant;
  }) => void;
  close: (slug: string) => void;
  focus: (slug: string) => void;
  minimize: (slug: string) => void;
  maximize: (slug: string) => void;
  /** Restore a minimized or maximized window to windowed state. */
  restore: (slug: string) => void;
  /** Mutate position+size; called by drag/resize handlers. */
  setGeometry: (slug: string, geometry: WindowGeometry) => void;

  /** Test-only reset. */
  _reset: () => void;
}

const STARTING_Z = 100;
/** Default open geometry — centered-ish, comfortably sub-screen. */
const DEFAULT_WIDTH = 960;
const DEFAULT_HEIGHT = 640;
/** Cascade offset for stacked windows. */
const CASCADE_PX = 32;
const STORAGE_PREFIX = 'atrium:layout:';

function isBrowser(): boolean {
  return typeof window !== 'undefined' && typeof localStorage !== 'undefined';
}

function loadGeometry(slug: string): WindowGeometry | null {
  if (!isBrowser()) return null;
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + slug);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<WindowGeometry>;
    if (
      typeof parsed.x === 'number' &&
      typeof parsed.y === 'number' &&
      typeof parsed.width === 'number' &&
      typeof parsed.height === 'number' &&
      parsed.width > 0 &&
      parsed.height > 0
    ) {
      return { x: parsed.x, y: parsed.y, width: parsed.width, height: parsed.height };
    }
  } catch {
    // Corrupted localStorage entry — fall through to default.
  }
  return null;
}

function saveGeometry(slug: string, geometry: WindowGeometry): void {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(STORAGE_PREFIX + slug, JSON.stringify(geometry));
  } catch {
    // Quota exceeded or storage disabled — silent no-op. Geometry will
    // be re-saved on the next move/resize anyway.
  }
}

function defaultGeometry(openWindowCount: number): WindowGeometry {
  // Cascade to give visual offset when multiple windows open in a row.
  const offset = (openWindowCount % 8) * CASCADE_PX;
  // Center on a typical 1440x900 viewport; the renderer clamps to the
  // actual viewport at mount time so we can be a little optimistic here.
  const baseX = Math.max(40, Math.floor((1440 - DEFAULT_WIDTH) / 2));
  const baseY = Math.max(40, Math.floor((900 - DEFAULT_HEIGHT) / 2));
  return {
    x: baseX + offset,
    y: baseY + offset,
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
  };
}

export const useAtriumStore = create<AtriumStore>((set, get) => ({
  windows: {},
  focusedSlug: null,
  zCounter: STARTING_Z,

  open: ({ slug, url, title, variant = 'app' }) => {
    const state = get();
    const existing = state.windows[slug];

    // Idempotent open: if this slug is already open, just bring it to
    // front and (when minimized) restore it. The iframe stays mounted
    // — its session state is preserved.
    if (existing) {
      const nextZ = state.zCounter + 1;
      set({
        windows: {
          ...state.windows,
          [slug]: {
            ...existing,
            state: existing.state === 'minimized' ? 'windowed' : existing.state,
            zIndex: nextZ,
          },
        },
        focusedSlug: slug,
        zCounter: nextZ,
      });
      return;
    }

    const persisted = loadGeometry(slug);
    const geometry = persisted ?? defaultGeometry(Object.keys(state.windows).length);
    const nextZ = state.zCounter + 1;

    set({
      windows: {
        ...state.windows,
        [slug]: {
          slug,
          url,
          title,
          variant,
          state: 'windowed',
          geometry,
          zIndex: nextZ,
          openedAt: Date.now(),
        },
      },
      focusedSlug: slug,
      zCounter: nextZ,
    });
  },

  close: (slug) => {
    const state = get();
    if (!state.windows[slug]) return;
    const { [slug]: _removed, ...rest } = state.windows;

    // Recompute focus: the window with the highest zIndex among
    // remaining non-minimized windows takes focus, else null.
    let nextFocused: string | null = null;
    let maxZ = -1;
    for (const w of Object.values(rest)) {
      if (w.state !== 'minimized' && w.zIndex > maxZ) {
        maxZ = w.zIndex;
        nextFocused = w.slug;
      }
    }
    set({ windows: rest, focusedSlug: nextFocused });
  },

  focus: (slug) => {
    const state = get();
    const target = state.windows[slug];
    if (!target) return;
    const nextZ = state.zCounter + 1;
    set({
      windows: {
        ...state.windows,
        [slug]: {
          ...target,
          // Focusing a minimized window also un-minimizes it (matches
          // macOS / Windows taskbar click semantics).
          state: target.state === 'minimized' ? 'windowed' : target.state,
          zIndex: nextZ,
        },
      },
      focusedSlug: slug,
      zCounter: nextZ,
    });
  },

  minimize: (slug) => {
    const state = get();
    const target = state.windows[slug];
    if (!target) return;
    set({
      windows: {
        ...state.windows,
        [slug]: { ...target, state: 'minimized' },
      },
      focusedSlug: state.focusedSlug === slug ? null : state.focusedSlug,
    });
  },

  maximize: (slug) => {
    const state = get();
    const target = state.windows[slug];
    if (!target) return;
    if (target.state === 'maximized') {
      // Toggle off → restore previous geometry.
      set({
        windows: {
          ...state.windows,
          [slug]: {
            ...target,
            state: 'windowed',
            geometry: target.prevGeometry ?? target.geometry,
            prevGeometry: undefined,
          },
        },
      });
      return;
    }
    const nextZ = state.zCounter + 1;
    set({
      windows: {
        ...state.windows,
        [slug]: {
          ...target,
          state: 'maximized',
          prevGeometry: target.geometry,
          zIndex: nextZ,
        },
      },
      focusedSlug: slug,
      zCounter: nextZ,
    });
  },

  restore: (slug) => {
    const state = get();
    const target = state.windows[slug];
    if (!target) return;
    set({
      windows: {
        ...state.windows,
        [slug]: {
          ...target,
          state: 'windowed',
          geometry: target.prevGeometry ?? target.geometry,
          prevGeometry: undefined,
        },
      },
    });
  },

  setGeometry: (slug, geometry) => {
    const state = get();
    const target = state.windows[slug];
    if (!target) return;
    // Persist user-driven geometry changes only when in windowed state
    // (maximized geometry is the full viewport and shouldn't overwrite
    // the user's preferred size).
    if (target.state === 'windowed') {
      saveGeometry(slug, geometry);
    }
    set({
      windows: {
        ...state.windows,
        [slug]: { ...target, geometry },
      },
    });
  },

  _reset: () => {
    set({ windows: {}, focusedSlug: null, zCounter: STARTING_Z });
  },
}));

/** Selector: ordered list of windows for rendering (low-z to high-z). */
export function selectWindowsZOrdered(
  s: Pick<AtriumStore, 'windows'>,
): AtriumWindow[] {
  return Object.values(s.windows).sort((a, b) => a.zIndex - b.zIndex);
}

/** Selector: ordered list for the taskbar (open order — stable). */
export function selectWindowsTaskbarOrdered(
  s: Pick<AtriumStore, 'windows'>,
): AtriumWindow[] {
  return Object.values(s.windows).sort((a, b) => a.openedAt - b.openedAt);
}
