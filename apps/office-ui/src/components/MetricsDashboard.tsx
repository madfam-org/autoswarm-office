'use client';

import { type FC } from 'react';
import { CloseButton } from '@selva/ui';
import { useMetrics, type MetricsPeriod } from '@/hooks/useMetrics';
import type { TrendPoint } from '@selva/shared-types';
import { formatHM } from '@/lib/format-time';

interface MetricsDashboardProps {
  open: boolean;
  onClose: () => void;
}

const PERIODS: MetricsPeriod[] = ['1h', '6h', '24h', '7d', '30d'];

/**
 * Inline SVG sparkline from an array of TrendPoints.
 * Zero-dependency alternative to chart libraries.
 */
const Sparkline: FC<{ data: TrendPoint[]; color: string }> = ({ data, color }) => {
  if (!data || data.length < 2) return null;

  const values = data.map((d) => d.value);
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 120;
  const h = 24;

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg width={w} height={h} className="inline-block">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

const StatCard: FC<{
  label: string;
  value: string;
  subtext?: string;
  color: string;
}> = ({ label, value, subtext, color }) => (
  <div className="retro-panel px-3 py-2 animate-fade-in-up">
    <p className="pixel-text text-[6px] uppercase text-slate-500">{label}</p>
    <p className={`font-mono text-lg font-bold ${color}`}>{value}</p>
    {subtext && (
      <p className="font-mono text-[7px] text-slate-500">{subtext}</p>
    )}
  </div>
);

export const MetricsDashboard: FC<MetricsDashboardProps> = ({
  open,
  onClose,
}) => {
  const { dashboard, loading, period, setPeriod } = useMetrics();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 animate-fade-in"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-slate-900 pixel-border-accent p-4 animate-pop-in">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="pixel-text text-sm uppercase tracking-wider text-amber-400">
            Ops Metrics
          </h2>
          <div className="flex items-center gap-3">
            {/* Period selector */}
            <div className="flex gap-1">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`px-2 py-0.5 font-mono text-[8px] uppercase ${
                    period === p
                      ? 'bg-amber-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:text-white'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
            <CloseButton onClick={onClose} label="Close metrics dashboard" shortcut="ESC" />
          </div>
        </div>

        {loading && !dashboard ? (
          <p role="status" className="py-12 text-center font-mono text-[9px] text-slate-500">
            Loading metrics...
          </p>
        ) : dashboard ? (
          <div className="space-y-4" aria-live="polite">
            {/* Stat cards grid */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <StatCard
                label="Utilization"
                value={`${dashboard.agent_utilization_pct.toFixed(1)}%`}
                color="text-cyan-400"
              />
              <StatCard
                label="Throughput"
                value={String(dashboard.task_throughput.total)}
                subtext={
                  dashboard.task_throughput.avg_duration_s
                    ? `avg ${dashboard.task_throughput.avg_duration_s}s`
                    : undefined
                }
                color="text-emerald-400"
              />
              <StatCard
                label="Approval Queue"
                value={String(dashboard.approval_latency.pending_count)}
                subtext={
                  dashboard.approval_latency.avg_seconds
                    ? `avg ${dashboard.approval_latency.avg_seconds}s`
                    : undefined
                }
                color="text-amber-400"
              />
              <StatCard
                label="Error Rate"
                value={`${dashboard.error_rate.toFixed(1)}%`}
                color={
                  dashboard.error_rate > 10
                    ? 'text-red-400'
                    : dashboard.error_rate > 5
                    ? 'text-amber-400'
                    : 'text-emerald-400'
                }
              />
            </div>

            {/* Sparklines */}
            <div className="grid grid-cols-2 gap-2">
              <div className="retro-panel px-3 py-2">
                <p className="pixel-text text-[6px] uppercase text-slate-500 mb-1">
                  Task Volume
                </p>
                <Sparkline data={dashboard.trends.tasks ?? []} color="#34d399" />
              </div>
              <div className="retro-panel px-3 py-2">
                <p className="pixel-text text-[6px] uppercase text-slate-500 mb-1">
                  Errors
                </p>
                <Sparkline data={dashboard.trends.errors ?? []} color="#f87171" />
              </div>
            </div>

            {/* Cost breakdown */}
            {dashboard.cost_breakdown.length > 0 && (
              <div className="retro-panel px-3 py-2">
                <p className="pixel-text text-[6px] uppercase text-slate-500 mb-2">
                  Cost by Provider
                </p>
                <div className="space-y-1">
                  {dashboard.cost_breakdown.map((row, i) => {
                    const maxTokens = Math.max(
                      ...dashboard.cost_breakdown.map((r) => r.total_tokens),
                      1,
                    );
                    const pct = (row.total_tokens / maxTokens) * 100;
                    return (
                      <div key={i} className="flex items-center gap-2">
                        <span className="w-20 truncate font-mono text-[7px] text-slate-400">
                          {row.provider}
                        </span>
                        <div className="flex-1 h-2 bg-slate-800 rounded-full">
                          <div
                            className="h-full bg-purple-500 rounded-full transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-16 text-right font-mono text-[7px] text-purple-400">
                          {row.total_tokens.toLocaleString()} tok
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Task status breakdown */}
            <div className="retro-panel px-3 py-2">
              <p className="pixel-text text-[6px] uppercase text-slate-500 mb-2">
                Task Status
              </p>
              <div className="flex gap-3 font-mono text-[8px]">
                {Object.entries(dashboard.task_throughput.status_counts).map(
                  ([status, count]) => (
                    <span key={status} className="text-slate-300">
                      <span
                        className={
                          status === 'completed'
                            ? 'text-emerald-400'
                            : status === 'failed'
                            ? 'text-red-400'
                            : status === 'running'
                            ? 'text-blue-400'
                            : 'text-slate-400'
                        }
                      >
                        {count}
                      </span>{' '}
                      {status}
                    </span>
                  ),
                )}
              </div>
            </div>

            {/* Recent errors */}
            {dashboard.recent_errors.length > 0 && (
              <div className="retro-panel px-3 py-2">
                <p className="pixel-text text-[6px] uppercase text-slate-500 mb-2">
                  Recent Errors
                </p>
                <div className="space-y-1 max-h-32 overflow-y-auto">
                  {dashboard.recent_errors.map((err) => (
                    <div
                      key={err.id}
                      className="border-l-2 border-l-red-500 bg-slate-800/40 px-2 py-1 font-mono text-[7px]"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-red-400">{err.event_type}</span>
                        <span className="text-slate-600">
                          {err.created_at ? formatHM(err.created_at) : ''}
                        </span>
                      </div>
                      {err.error_message && (
                        <p className="truncate text-slate-400">
                          {err.error_message}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="py-12 text-center font-mono text-[9px] text-slate-500">
            No metrics data available
          </p>
        )}
      </div>
    </div>
  );
};
