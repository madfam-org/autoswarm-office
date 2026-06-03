'use client';

import { useState, useEffect, useCallback } from 'react';
import { Button } from '@selva/ui';
import { apiFetch } from '@/lib/api';

interface BillingStatus {
  tier: string;
  daily_limit: number;
}

interface TokenUsage {
  used_today: number;
  daily_limit: number;
  remaining: number;
}

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [usage, setUsage] = useState<TokenUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, tokensRes] = await Promise.all([
        apiFetch('/api/v1/billing/status'),
        apiFetch('/api/v1/billing/tokens'),
      ]);

      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
      if (tokensRes.ok) {
        setUsage(await tokensRes.json());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load billing data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const usagePercent = usage ? Math.min(100, (usage.used_today / usage.daily_limit) * 100) : 0;

  return (
    <div className="min-h-screen bg-slate-900 px-6 py-8">
      <header className="mb-6">
        <nav className="mb-4">
          <a
            href="/"
            className="font-mono text-xs text-slate-500 hover:text-indigo-400"
          >
            &lt; Back to Dashboard
          </a>
        </nav>
        <h1 className="font-mono text-xl font-bold uppercase tracking-widest text-indigo-400">
          Billing &amp; Usage
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          Subscription tier and compute token usage
        </p>
      </header>

      {error && (
        <div className="mb-4 bg-red-900/30 px-4 py-3 font-mono text-sm text-red-400">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-4 text-red-300 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {loading ? (
        <p className="py-20 text-center font-mono text-sm text-slate-500 animate-pulse">
          Loading billing data...
        </p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Subscription Tier */}
          <div className="border border-slate-700 bg-slate-800/50 p-6">
            <h2 className="mb-4 font-mono text-sm font-bold uppercase tracking-wider text-slate-400">
              Subscription Tier
            </h2>
            <p className="text-3xl font-bold text-indigo-400">
              {status?.tier ?? 'Unknown'}
            </p>
            <p className="mt-2 font-mono text-xs text-slate-500">
              Daily limit: {status?.daily_limit?.toLocaleString() ?? '—'} tokens
            </p>
            <div className="mt-4">
              <a
                href={process.env.NEXT_PUBLIC_DHANAM_URL ?? 'https://api.dhan.am'}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button size="sm" variant="outline">
                  Manage Subscription
                </Button>
              </a>
            </div>
          </div>

          {/* Daily Token Usage */}
          <div className="border border-slate-700 bg-slate-800/50 p-6">
            <h2 className="mb-4 font-mono text-sm font-bold uppercase tracking-wider text-slate-400">
              Daily Token Usage
            </h2>
            <p className="text-3xl font-bold text-white">
              {usage?.used_today?.toLocaleString() ?? '0'}
              <span className="text-lg text-slate-500">
                {' '}/ {usage?.daily_limit?.toLocaleString() ?? '—'}
              </span>
            </p>
            <div className="mt-3 h-3 w-full overflow-hidden bg-slate-700">
              <div
                className={`h-full transition-all ${
                  usagePercent > 90
                    ? 'bg-red-500'
                    : usagePercent > 70
                      ? 'bg-amber-500'
                      : 'bg-indigo-500'
                }`}
                style={{ width: `${usagePercent}%` }}
              />
            </div>
            <p className="mt-2 font-mono text-xs text-slate-500">
              {usage?.remaining?.toLocaleString() ?? '—'} tokens remaining today
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
