'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import type {
  Agent,
  ComputeTokenBucket,
  Department,
} from '@autoswarm/shared-types';

const NEXUS_API_URL =
  process.env.NEXT_PUBLIC_NEXUS_API_URL ?? 'http://localhost:4300';

interface SystemOverview {
  totalAgents: number;
  totalDepartments: number;
  pendingApprovals: number;
  computeTokens: ComputeTokenBucket;
  agents: Agent[];
  departments: Department[];
}

const NAV_LINKS = [
  { href: '/agents', label: 'Agents', description: 'Manage AI agents' },
  {
    href: '/permissions',
    label: 'Permissions',
    description: 'Configure permission matrix',
  },
  { href: '/billing', label: 'Billing', description: 'Subscription & tokens' },
  { href: '/health', label: 'Health', description: 'System status' },
] as const;

export default function AdminDashboard() {
  const [overview, setOverview] = useState<SystemOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchOverview() {
      try {
        const [agentsRes, depsRes, approvalsRes, tokensRes] = await Promise.all(
          [
            fetch(`${NEXUS_API_URL}/api/v1/agents`),
            fetch(`${NEXUS_API_URL}/api/v1/departments`),
            fetch(`${NEXUS_API_URL}/api/v1/approvals/pending`),
            fetch(`${NEXUS_API_URL}/api/v1/billing/tokens`),
          ],
        );

        const agents: Agent[] = agentsRes.ok ? await agentsRes.json() : [];
        const departments: Department[] = depsRes.ok
          ? await depsRes.json()
          : [];
        const pendingApprovals: { count: number } = approvalsRes.ok
          ? await approvalsRes.json()
          : { count: 0 };
        const computeTokens: ComputeTokenBucket = tokensRes.ok
          ? await tokensRes.json()
          : { dailyLimit: 10000, used: 0, remaining: 10000, resetAt: '' };

        setOverview({
          totalAgents: agents.length,
          totalDepartments: departments.length,
          pendingApprovals: pendingApprovals.count,
          computeTokens,
          agents,
          departments,
        });
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to load dashboard data',
        );
      } finally {
        setLoading(false);
      }
    }

    fetchOverview();
  }, []);

  const tokenPercent = overview
    ? Math.min(
        (overview.computeTokens.used / overview.computeTokens.dailyLimit) * 100,
        100,
      )
    : 0;

  return (
    <div className="min-h-screen bg-slate-900 px-6 py-8">
      {/* Header */}
      <header className="mb-8">
        <h1 className="font-mono text-2xl font-bold uppercase tracking-widest text-indigo-400">
          AutoSwarm Admin
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          System administration and configuration
        </p>
      </header>

      {loading && (
        <div className="flex items-center justify-center py-20">
          <p className="font-mono text-sm text-slate-500 animate-pulse">
            Loading dashboard...
          </p>
        </div>
      )}

      {error && (
        <div className="mb-6 bg-red-900/30 px-4 py-3 pixel-border font-mono text-sm text-red-400">
          Error: {error}
        </div>
      )}

      {overview && (
        <>
          {/* Stats cards */}
          <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Total Agents"
              value={overview.totalAgents}
              color="text-cyan-400"
            />
            <StatCard
              label="Departments"
              value={overview.totalDepartments}
              color="text-indigo-400"
            />
            <StatCard
              label="Pending Approvals"
              value={overview.pendingApprovals}
              color="text-amber-400"
              alert={overview.pendingApprovals > 0}
            />
            <div className="bg-slate-800 px-5 py-4 pixel-border">
              <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
                Compute Tokens
              </p>
              <p className="mt-1 font-mono text-xl font-bold text-emerald-400">
                {overview.computeTokens.remaining.toLocaleString()}
              </p>
              <div className="mt-2 h-2 w-full bg-slate-900">
                <div
                  className={`h-full transition-all ${
                    tokenPercent > 80
                      ? 'bg-red-500'
                      : tokenPercent > 50
                        ? 'bg-amber-500'
                        : 'bg-emerald-500'
                  }`}
                  style={{ width: `${tokenPercent}%` }}
                />
              </div>
              <p className="mt-1 font-mono text-[9px] text-slate-600">
                {overview.computeTokens.used.toLocaleString()} /{' '}
                {overview.computeTokens.dailyLimit.toLocaleString()} used
              </p>
            </div>
          </div>

          {/* Navigation cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="group bg-slate-800 px-5 py-4 pixel-border transition-all hover:pixel-border-accent"
              >
                <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-white group-hover:text-indigo-400">
                  {link.label}
                </h3>
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {link.description}
                </p>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
  alert,
}: {
  label: string;
  value: number;
  color: string;
  alert?: boolean;
}) {
  return (
    <div className="relative bg-slate-800 px-5 py-4 pixel-border">
      <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className={`mt-1 font-mono text-2xl font-bold ${color}`}>{value}</p>
      {alert && (
        <span className="absolute right-3 top-3 inline-block h-3 w-3 rounded-full bg-red-500 animate-pulse" />
      )}
    </div>
  );
}
