'use client';

/**
 * Dragon-egg admin surface.
 *
 * Phase 1: admin-only. The middleware (``apps/office-ui/src/middleware.ts``)
 * redirects unauthenticated users to /login. The admin gate here
 * additionally rejects authenticated non-admin users — they see a
 * 403 panel rather than a redirect, since they ARE logged in,
 * just not entitled to this page yet.
 *
 * Phase 2 will replace the admin gate with a tenant-feature-flag
 * check; the page surface below is forward-compatible.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

import { getSessionUser, isAdmin } from '@/lib/api';
import { listEggs } from '@/components/dragon-eggs/api';
import { EggDetail } from '@/components/dragon-eggs/EggDetail';
import { EggGrid } from '@/components/dragon-eggs/EggGrid';
import { LayEggForm } from '@/components/dragon-eggs/LayEggForm';
import {
  EGG_STATUS_LABELS,
  EGG_STATUS_ORDER,
  PLATFORM_LABELS,
  type Egg,
  type EggPlatform,
  type EggStatus,
} from '@/components/dragon-eggs/types';

const ADMIN_EMAILS = new Set(['admin@madfam.io']);

function isDragonEggAdmin(): boolean {
  const user = getSessionUser();
  if (!user) return false;
  if (ADMIN_EMAILS.has(user.email)) return true;
  return isAdmin();
}

export default function DragonEggsPage() {
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [eggs, setEggs] = useState<Egg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layFormOpen, setLayFormOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<EggStatus | ''>('');
  const [platformFilter, setPlatformFilter] = useState<EggPlatform | ''>('');

  // Resolve auth client-side. Server components don't have access to
  // the JWT cookie's payload without re-implementing decode, so we
  // gate on the client. The middleware has already enforced "logged
  // in".
  useEffect(() => {
    setAuthorized(isDragonEggAdmin());
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const list = await listEggs({
        status: statusFilter || undefined,
        platform: platformFilter || undefined,
      });
      setEggs(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load eggs');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, platformFilter]);

  useEffect(() => {
    if (authorized) void refresh();
  }, [authorized, refresh]);

  const stats = useMemo(() => {
    const counts: Record<EggStatus, number> = {
      laid: 0,
      incubating: 0,
      hatching: 0,
      hatched: 0,
      matured: 0,
    };
    for (const e of eggs) counts[e.status] += 1;
    return counts;
  }, [eggs]);

  if (authorized === null) {
    return (
      <main className="min-h-screen bg-slate-950 p-8 text-slate-100" aria-busy="true">
        <p className="text-sm text-slate-400">Loading…</p>
      </main>
    );
  }

  if (!authorized) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 p-8 text-slate-100">
        <div
          className="max-w-md space-y-4 rounded-md border border-slate-800 bg-slate-900/60 p-8 text-center"
          role="alert"
          aria-labelledby="dragon-403-title"
        >
          <h1 id="dragon-403-title" className="text-base font-semibold text-slate-200">
            Not authorized
          </h1>
          <p className="text-sm text-slate-400">
            Dragon eggs are admin-only in Phase 1. Phase 2 opens this surface
            to tenants with the feature entitlement.
          </p>
          <Link
            href="/office"
            className="inline-block rounded-md border border-slate-700 px-4 py-2 text-xs uppercase tracking-wider text-slate-300 hover:border-slate-600"
          >
            ← Back to office
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <Link href="/office" className="text-xs text-solarpunk-glass hover:text-solarpunk-glass/80">
              ← Back to office
            </Link>
            <h1 className="text-2xl font-semibold text-slate-100">Dragon eggs</h1>
            <p className="text-sm text-slate-400">
              Lay an egg, watch it incubate, then watch it hatch into a
              dragon. The 7-day warmup curve mirrors the campaign launch
              runbook §4.2.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setLayFormOpen(true)}
            className="rounded-md border border-solarpunk-solar/60 bg-solarpunk-solar/10 px-4 py-2 text-sm font-medium text-solarpunk-solar transition hover:bg-solarpunk-solar/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
          >
            Lay an egg
          </button>
        </header>

        <section
          className="grid grid-cols-2 gap-3 sm:grid-cols-5"
          aria-label="Egg counts by status"
        >
          {EGG_STATUS_ORDER.map((s) => (
            <div key={s} className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">
                {EGG_STATUS_LABELS[s]}
              </p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-slate-100">
                {stats[s]}
              </p>
            </div>
          ))}
        </section>

        <section className="flex flex-wrap items-center gap-2 text-xs">
          <label className="text-slate-400">
            Status
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as EggStatus | '')}
              className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200"
            >
              <option value="">All</option>
              {EGG_STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {EGG_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-slate-400">
            Platform
            <select
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value as EggPlatform | '')}
              className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200"
            >
              <option value="">All</option>
              {(['mastodon', 'bluesky', 'reddit'] as EggPlatform[]).map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABELS[p]}
                </option>
              ))}
            </select>
          </label>
        </section>

        <EggGrid
          eggs={eggs}
          loading={loading}
          error={error}
          onSelect={(egg) => setSelected(egg.id)}
          onLayFirst={() => setLayFormOpen(true)}
        />
      </div>

      {layFormOpen && (
        <LayEggForm
          onClose={() => setLayFormOpen(false)}
          onLaid={() => {
            setLayFormOpen(false);
            void refresh();
          }}
        />
      )}

      {selected && (
        <EggDetail
          eggId={selected}
          onClose={() => setSelected(null)}
          onChanged={() => void refresh()}
        />
      )}
    </main>
  );
}
