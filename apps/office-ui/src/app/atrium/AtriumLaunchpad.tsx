'use client';

/**
 * AtriumLaunchpad — client component for the /atrium full-grid view.
 *
 * Shows every platform in the catalog as a tile, grouped by tier.
 * Clicking a tile opens that platform as a window in the Atrium store
 * and routes the user back to /office so the window is immediately
 * visible inside the office shell.
 *
 * Admin-only entries are filtered via useIsMadfamAdmin (default-deny).
 * Admin URL variants are surfaced when the operator is an admin and
 * the catalog entry has an adminUrl.
 */

import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  ATRIUM_CATALOG,
  resolveLaunchUrl,
  visibleCatalog,
  type AtriumPlatform,
  type PlatformTier,
} from '@/lib/atrium/catalog';
import { useAtriumStore } from '@/stores/atrium-windows';
import { useIsMadfamAdmin } from '@/hooks/useIsMadfamAdmin';

const TIER_LABELS: Record<PlatformTier, string> = {
  'self-serve': 'Self-serve products',
  platform: 'Platform infrastructure',
  'ecosystem-service': 'Ecosystem services',
};

const TIER_ORDER: readonly PlatformTier[] = [
  'self-serve',
  'platform',
  'ecosystem-service',
] as const;

const TIER_TILE: Record<PlatformTier, string> = {
  'self-serve': 'border-emerald-700/60 hover:border-emerald-500',
  platform: 'border-violet-700/60 hover:border-violet-500',
  'ecosystem-service': 'border-sky-700/60 hover:border-sky-500',
};

export function AtriumLaunchpad() {
  const router = useRouter();
  const isAdmin = useIsMadfamAdmin();
  const open = useAtriumStore((s) => s.open);

  const visible = visibleCatalog(isAdmin);

  const handleLaunch = useCallback(
    (entry: AtriumPlatform, variant: 'app' | 'admin' | 'public') => {
      const url = resolveLaunchUrl(entry, variant);
      if (!url) return;
      open({ slug: entry.slug, url, title: entry.displayName, variant });
      // Per spec: clicking a tile opens the window AND navigates back
      // to the office canvas so the operator immediately sees it.
      router.push('/office');
    },
    [open, router],
  );

  const grouped: Record<PlatformTier, AtriumPlatform[]> = {
    'self-serve': [],
    platform: [],
    'ecosystem-service': [],
  };
  for (const entry of visible) {
    grouped[entry.tier].push(entry);
  }

  return (
    <main
      data-testid="atrium-launchpad"
      className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100"
    >
      <header className="mx-auto mb-10 max-w-5xl">
        <p className="mb-2 font-mono text-xs uppercase tracking-widest text-emerald-400">
          MADFAM Ecosystem
        </p>
        <h1 className="text-3xl font-bold sm:text-4xl">Welcome to the Atrium</h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
          The Atrium is the central space inside the Selva office where every
          MADFAM platform converges. Pick a platform below — it opens as a
          draggable window over your office canvas. Your office stays right
          where it is.
        </p>
      </header>

      <div className="mx-auto max-w-5xl space-y-8">
        {TIER_ORDER.map((tier) => {
          const entries = grouped[tier];
          if (entries.length === 0) return null;
          return (
            <section key={tier} aria-labelledby={`atrium-tier-${tier}`}>
              <h2
                id={`atrium-tier-${tier}`}
                className="mb-3 font-mono text-xs uppercase tracking-widest text-slate-500"
              >
                {TIER_LABELS[tier]}
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {entries.map((entry) => {
                  const launchUrl = resolveLaunchUrl(entry, 'app');
                  const disabled = !launchUrl;
                  return (
                    <article
                      key={entry.slug}
                      data-testid={`atrium-launchpad-tile-${entry.slug}`}
                      className={`rounded-lg border bg-slate-900 p-4 transition ${TIER_TILE[entry.tier]} ${
                        disabled ? 'opacity-60' : ''
                      }`}
                    >
                      <div className="mb-2 flex items-center justify-between">
                        <h3 className="text-base font-semibold">{entry.displayName}</h3>
                        <span className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                          {entry.tier}
                        </span>
                      </div>
                      <p className="mb-4 text-xs leading-relaxed text-slate-400">
                        {entry.tagline}
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleLaunch(entry, 'app')}
                          disabled={disabled}
                          data-testid={`atrium-launchpad-tile-${entry.slug}-open`}
                          aria-label={
                            disabled
                              ? `${entry.displayName} (unavailable)`
                              : `Open ${entry.displayName} in Atrium`
                          }
                          className={`rounded px-3 py-1.5 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${
                            disabled
                              ? 'cursor-not-allowed bg-slate-800 text-slate-500'
                              : 'bg-emerald-600 text-white hover:bg-emerald-500'
                          }`}
                        >
                          Open in Atrium
                        </button>
                        {isAdmin && entry.adminUrl && (
                          <button
                            type="button"
                            onClick={() => handleLaunch(entry, 'admin')}
                            data-testid={`atrium-launchpad-tile-${entry.slug}-admin`}
                            className="rounded bg-amber-500/20 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-amber-300 hover:bg-amber-500/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
                            aria-label={`Open ${entry.displayName} admin console in Atrium`}
                          >
                            Admin
                          </button>
                        )}
                        {entry.publicUrl && (
                          <a
                            href={entry.publicUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500 hover:text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
                          >
                            Public site ↗
                          </a>
                        )}
                        {disabled && (
                          <span className="font-mono text-[10px] italic text-slate-500">
                            unavailable
                          </span>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
        {visible.length === 0 && (
          <p
            className="text-sm text-slate-500"
            data-testid="atrium-launchpad-empty"
          >
            No platforms are currently visible to your account.
          </p>
        )}
      </div>

      <footer className="mx-auto mt-12 max-w-5xl border-t border-slate-800 pt-6 text-xs text-slate-500">
        Catalog derived from the live MADFAM ecosystem ({ATRIUM_CATALOG.length}{' '}
        platforms). Some embeds may fall back to &ldquo;open in new tab&rdquo;
        when the platform&apos;s X-Frame-Options or CSP frame-ancestors
        forbids embedding.
      </footer>
    </main>
  );
}
