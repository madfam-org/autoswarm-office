'use client';

/**
 * AtriumDock — sidebar launcher for the Atrium.
 *
 * Renders a vertical strip of platform icons on the left edge of the
 * office shell. Clicking an icon opens (or focuses) the corresponding
 * EcosystemWindow.
 *
 * The dock respects admin gating: non-admin operators only see
 * non-adminOnly entries, and the admin variant is launchable only
 * when the operator is an admin AND the entry has an adminUrl.
 *
 * Tile layout: each platform shows the first letter of its name in
 * a colored tile (color derived from tier). Hovering reveals the
 * full name + tagline as a tooltip-style label.
 */

import { useCallback } from 'react';
import {
  ATRIUM_CATALOG,
  resolveLaunchUrl,
  visibleCatalog,
  type AtriumPlatform,
  type PlatformTier,
} from '@/lib/atrium/catalog';
import { useAtriumStore } from '@/stores/atrium-windows';
import { useIsMadfamAdmin } from '@/hooks/useIsMadfamAdmin';

const TIER_COLORS: Record<PlatformTier, { bg: string; ring: string; text: string }> = {
  'self-serve': {
    bg: 'bg-emerald-600',
    ring: 'ring-emerald-400',
    text: 'text-emerald-50',
  },
  platform: {
    bg: 'bg-violet-600',
    ring: 'ring-violet-400',
    text: 'text-violet-50',
  },
  'ecosystem-service': {
    bg: 'bg-sky-600',
    ring: 'ring-sky-400',
    text: 'text-sky-50',
  },
};

interface AtriumDockProps {
  /** Optional className extension for layout integration. */
  className?: string;
}

export function AtriumDock({ className = '' }: AtriumDockProps) {
  const isAdmin = useIsMadfamAdmin();
  const open = useAtriumStore((s) => s.open);
  const focus = useAtriumStore((s) => s.focus);
  const focusedSlug = useAtriumStore((s) => s.focusedSlug);
  const windows = useAtriumStore((s) => s.windows);

  const visible = visibleCatalog(isAdmin);

  const handleLaunch = useCallback(
    (entry: AtriumPlatform, variant: 'app' | 'admin' | 'public') => {
      const url = resolveLaunchUrl(entry, variant);
      if (!url) return;
      // If already open, focus to bring to front.
      if (windows[entry.slug]) {
        focus(entry.slug);
        return;
      }
      open({
        slug: entry.slug,
        url,
        title: entry.displayName,
        variant,
      });
    },
    [windows, open, focus],
  );

  return (
    <nav
      data-testid="atrium-dock"
      aria-label="Atrium platform launcher"
      className={`pointer-events-auto flex flex-col gap-1 rounded-r-lg border border-l-0 border-slate-700 bg-slate-900/90 p-1.5 backdrop-blur-sm ${className}`}
    >
      <div className="px-1 pb-1 text-center font-mono text-[8px] uppercase tracking-widest text-slate-400">
        Atrium
      </div>
      {ATRIUM_CATALOG.length > 0 && visible.length === 0 && (
        <div className="px-2 py-1 text-[10px] text-slate-500" data-testid="atrium-dock-empty">
          No platforms available
        </div>
      )}
      {visible.map((entry) => {
        const launchableUrl = resolveLaunchUrl(entry, 'app');
        const disabled = !launchableUrl;
        const isOpen = !!windows[entry.slug];
        const isFocused = focusedSlug === entry.slug;
        const colors = TIER_COLORS[entry.tier];

        return (
          <div key={entry.slug} className="group relative">
            <button
              type="button"
              onClick={() => !disabled && handleLaunch(entry, 'app')}
              disabled={disabled}
              data-testid={`atrium-dock-${entry.slug}`}
              data-tier={entry.tier}
              data-open={isOpen ? 'true' : 'false'}
              aria-label={
                disabled
                  ? `${entry.displayName} (unavailable)`
                  : isOpen
                    ? `Focus ${entry.displayName}`
                    : `Open ${entry.displayName} in Atrium`
              }
              className={`flex h-10 w-10 items-center justify-center rounded font-mono text-sm font-bold transition ${
                disabled
                  ? 'cursor-not-allowed bg-slate-800 text-slate-600 opacity-50'
                  : `${colors.bg} ${colors.text} hover:scale-105 hover:brightness-110 active:scale-95`
              } ${
                isFocused
                  ? `ring-2 ring-offset-1 ring-offset-slate-900 ${colors.ring}`
                  : ''
              } ${isOpen && !isFocused ? 'opacity-80' : ''} focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300`}
            >
              {entry.displayName.charAt(0).toUpperCase()}
            </button>
            {/* Hover label — pointer-events-none so it doesn't steal hover */}
            <div
              role="tooltip"
              className="pointer-events-none absolute left-12 top-0 z-50 hidden whitespace-nowrap rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100 shadow-lg group-hover:block"
            >
              <div className="font-medium">{entry.displayName}</div>
              <div className="text-slate-400">{entry.tagline}</div>
              {isAdmin && entry.adminUrl && !disabled && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleLaunch(entry, 'admin');
                  }}
                  className="mt-1 pointer-events-auto block w-full rounded bg-amber-500/20 px-1.5 py-0.5 text-left font-mono text-[10px] uppercase text-amber-300 hover:bg-amber-500/30"
                  data-testid={`atrium-dock-${entry.slug}-admin`}
                >
                  Open admin
                </button>
              )}
              {disabled && (
                <div className="mt-0.5 italic text-slate-500">unavailable</div>
              )}
            </div>
          </div>
        );
      })}
    </nav>
  );
}
