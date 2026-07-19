'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useCheckout } from '@/hooks/useCheckout';
import { ToastProvider } from '@/components/Toast';
import { ThemeToggle } from '@/components/ThemeToggle';

/**
 * /pricing — Selva subscription tiers with a real checkout CTA (M1).
 *
 * Tiers come from the API (`/billing/tiers`, sourced from the canonical
 * infra/pricing/selva-tiers.json), so the numbers can never drift from the
 * pricing source of truth. Each "Choose" button starts a real Dhanam-backed
 * checkout via useCheckout; while Dhanam's checkout API is not yet live the
 * hook shows a truthful "coming soon" toast instead of a dead link.
 */

interface Tier {
  slug: string;
  name: string;
  daily_token_limit: number;
  stripe_price_id_env_key?: string | null;
}

const TIER_BLURB: Record<string, string> = {
  starter: 'For getting a feel for your AI workforce.',
  professional: 'For solo operators running real daily work.',
  enterprise: 'For teams that need serious daily throughput.',
};

function PricingInner() {
  const [tiers, setTiers] = useState<Tier[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const { loading, startCheckout } = useCheckout();
  const [pendingTier, setPendingTier] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const resp = await apiFetch('/api/v1/billing/tiers');
        if (!resp.ok) throw new Error(String(resp.status));
        const data = (await resp.json()) as { tiers: Tier[] };
        if (active) setTiers(data.tiers);
      } catch {
        if (active) setLoadError(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const choose = useCallback(
    (slug: string) => {
      setPendingTier(slug);
      void startCheckout(slug);
    },
    [startCheckout],
  );

  return (
    <main className="min-h-screen bg-surface px-4 py-16">
      <div className="fixed left-4 top-4">
        <ThemeToggle />
      </div>

      <div className="mx-auto max-w-4xl">
        <header className="mb-12 text-center">
          <h1 className="text-3xl font-semibold text-ink">Choose your plan</h1>
          <p className="mt-2 text-sm text-ink-muted">
            Every plan sets your daily compute budget. Upgrade any time — your
            agents keep working.
          </p>
        </header>

        {loadError && (
          <p className="text-center text-sm text-ink-muted">
            Couldn&apos;t load plans right now. Please refresh.
          </p>
        )}

        {!tiers && !loadError && (
          <p className="text-center text-sm text-ink-muted">Loading plans…</p>
        )}

        {tiers && (
          <div className="grid gap-6 md:grid-cols-3">
            {tiers.map((tier) => (
              <div
                key={tier.slug}
                className="flex flex-col rounded-2xl border border-edge bg-surface-raised p-6"
              >
                <h2 className="text-lg font-semibold capitalize text-ink">
                  {tier.name}
                </h2>
                <p className="mt-1 min-h-[2.5rem] text-xs text-ink-muted">
                  {TIER_BLURB[tier.slug] ?? ''}
                </p>
                <p className="mt-4 text-2xl font-semibold text-accent">
                  {tier.daily_token_limit.toLocaleString()}
                  <span className="ml-1 text-sm font-normal text-ink-muted">
                    tokens / day
                  </span>
                </p>
                <button
                  type="button"
                  onClick={() => choose(tier.slug)}
                  disabled={loading}
                  className="mt-6 w-full rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {loading && pendingTier === tier.slug
                    ? 'Starting checkout…'
                    : 'Choose'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

export default function PricingPage() {
  return (
    <ToastProvider>
      <PricingInner />
    </ToastProvider>
  );
}
