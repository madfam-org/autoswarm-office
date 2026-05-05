'use client';

/**
 * AtriumTaskbar — bottom-of-shell strip of chips, one per open window.
 *
 * Click a chip to focus the window. Right-click (or middle-click) to
 * close it without first focusing. Minimized windows are visually
 * distinct (faded + dashed border) so the operator can tell at a
 * glance which platforms are dehydrated to the taskbar.
 *
 * Hidden when there are no open windows so it doesn't clutter the
 * office canvas during normal use.
 */

import { useCallback, type MouseEvent } from 'react';
import {
  selectWindowsTaskbarOrdered,
  useAtriumStore,
} from '@/stores/atrium-windows';

export function AtriumTaskbar(): JSX.Element | null {
  const windows = useAtriumStore((s) => s.windows);
  const focusedSlug = useAtriumStore((s) => s.focusedSlug);
  const focus = useAtriumStore((s) => s.focus);
  const close = useAtriumStore((s) => s.close);

  const ordered = selectWindowsTaskbarOrdered({ windows });

  const onChipClick = useCallback(
    (slug: string) => () => {
      focus(slug);
    },
    [focus],
  );

  const onChipContextMenu = useCallback(
    (slug: string) => (e: MouseEvent) => {
      e.preventDefault();
      close(slug);
    },
    [close],
  );

  const onChipAuxClick = useCallback(
    (slug: string) => (e: MouseEvent) => {
      // Middle-click closes too — common SPA convention.
      if (e.button === 1) {
        e.preventDefault();
        close(slug);
      }
    },
    [close],
  );

  if (ordered.length === 0) return null;

  return (
    <div
      data-testid="atrium-taskbar"
      role="toolbar"
      aria-label="Open Atrium windows"
      className="pointer-events-auto fixed bottom-0 left-1/2 z-30 flex max-w-[90vw] -translate-x-1/2 flex-wrap items-center gap-1 rounded-t-lg border border-b-0 border-slate-700 bg-slate-900/90 px-2 py-1 backdrop-blur-sm"
    >
      {ordered.map((w) => {
        const isFocused = focusedSlug === w.slug;
        const isMinimized = w.state === 'minimized';
        return (
          <button
            key={w.slug}
            type="button"
            onClick={onChipClick(w.slug)}
            onContextMenu={onChipContextMenu(w.slug)}
            onAuxClick={onChipAuxClick(w.slug)}
            data-testid={`atrium-taskbar-chip-${w.slug}`}
            data-state={w.state}
            data-focused={isFocused ? 'true' : 'false'}
            aria-label={`${w.title} — ${w.state}. Click to focus, right-click to close.`}
            className={`flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] transition ${
              isMinimized
                ? 'border border-dashed border-slate-600 bg-slate-800/50 text-slate-400'
                : isFocused
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
            } focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                isMinimized
                  ? 'bg-slate-500'
                  : isFocused
                    ? 'bg-emerald-200'
                    : 'bg-emerald-500'
              }`}
              aria-hidden="true"
            />
            <span className="truncate">{w.title}</span>
            {w.variant === 'admin' && (
              <span className="font-mono text-[9px] uppercase text-amber-400" aria-hidden="true">
                admin
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
