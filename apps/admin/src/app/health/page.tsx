'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

interface HealthCheck {
  component: string;
  status: 'healthy' | 'unhealthy' | 'unknown';
  latency_ms?: number;
}

interface HealthDetail {
  status: string;
  checks: HealthCheck[];
}

const STATUS_COLORS: Record<string, string> = {
  healthy: 'bg-emerald-500',
  unhealthy: 'bg-red-500',
  unknown: 'bg-slate-500',
};

const STATUS_TEXT_COLORS: Record<string, string> = {
  healthy: 'text-emerald-400',
  unhealthy: 'text-red-400',
  unknown: 'text-slate-400',
};

export default function HealthPage() {
  const [health, setHealth] = useState<HealthDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await apiFetch('/api/v1/health/detail');
      if (res.ok) {
        setHealth(await res.json());
      } else {
        setError('Failed to fetch health status');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

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
          System Health
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          Infrastructure component status (auto-refreshes every 15s)
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
          Checking system health...
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {health?.checks.map((check) => (
            <div
              key={check.component}
              className="border border-slate-700 bg-slate-800/50 p-5"
            >
              <div className="flex items-center gap-3">
                <div
                  className={`h-3 w-3 rounded-full ${STATUS_COLORS[check.status] ?? STATUS_COLORS.unknown}`}
                />
                <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-white">
                  {check.component}
                </h3>
              </div>
              <p
                className={`mt-2 font-mono text-xs font-bold uppercase ${STATUS_TEXT_COLORS[check.status] ?? STATUS_TEXT_COLORS.unknown}`}
              >
                {check.status}
              </p>
              {check.latency_ms !== undefined && (
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {check.latency_ms}ms latency
                </p>
              )}
            </div>
          ))}

          {(!health?.checks || health.checks.length === 0) && (
            <p className="col-span-full py-12 text-center font-mono text-sm text-slate-600">
              No health checks available
            </p>
          )}
        </div>
      )}
    </div>
  );
}
