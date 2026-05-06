'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface DeploymentEvidenceRecord {
  id: string;
  task_id: string;
  graph_type: string;
  deployment_status: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

interface DeploymentEvidenceListResponse {
  evidence_records: DeploymentEvidenceRecord[];
  total: number;
  limit: number;
  offset: number;
}

type PhaseSummary = {
  phase: string;
  status: string;
};

const STATUS_COLORS: Record<string, string> = {
  passed: 'text-emerald-400 border-emerald-500/40 bg-emerald-950/30',
  recorded: 'text-emerald-400 border-emerald-500/40 bg-emerald-950/30',
  deployed: 'text-emerald-400 border-emerald-500/40 bg-emerald-950/30',
  completed: 'text-emerald-400 border-emerald-500/40 bg-emerald-950/30',
  synced: 'text-cyan-400 border-cyan-500/40 bg-cyan-950/30',
  healthy: 'text-cyan-400 border-cyan-500/40 bg-cyan-950/30',
  skipped: 'text-amber-400 border-amber-500/40 bg-amber-950/30',
  failed: 'text-red-400 border-red-500/40 bg-red-950/30',
  error: 'text-red-400 border-red-500/40 bg-red-950/30',
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function summarizePhases(evidence: Record<string, unknown>): PhaseSummary[] {
  return Object.entries(evidence)
    .filter(([, value]) => value && typeof value === 'object')
    .map(([phase, value]) => {
      const data = value as Record<string, unknown>;
      const rawStatus =
        data.status ?? data.result ?? data.phase_status ?? data.health_status;
      return {
        phase,
        status: rawStatus == null ? 'recorded' : String(rawStatus),
      };
    });
}

function statusClass(status: string): string {
  return (
    STATUS_COLORS[status.toLowerCase()] ??
    'text-slate-300 border-slate-600 bg-slate-800/70'
  );
}

function EvidencePhaseSummary({
  evidence,
}: {
  evidence: Record<string, unknown>;
}) {
  const phases = summarizePhases(evidence);

  if (phases.length === 0) {
    return <span className="text-slate-600">No phase evidence</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {phases.slice(0, 6).map((phase) => (
        <span
          key={phase.phase}
          className={`border px-1.5 py-0.5 text-[10px] uppercase ${statusClass(
            phase.status,
          )}`}
          title={`${phase.phase}: ${phase.status}`}
        >
          {phase.phase}: {phase.status}
        </span>
      ))}
      {phases.length > 6 && (
        <span className="border border-slate-700 bg-slate-800/70 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">
          +{phases.length - 6} more
        </span>
      )}
    </div>
  );
}

export default function DeploymentEvidencePage() {
  const [records, setRecords] = useState<DeploymentEvidenceRecord[]>([]);
  const [selected, setSelected] = useState<DeploymentEvidenceRecord | null>(
    null,
  );
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskFilter, setTaskFilter] = useState('');

  const fetchEvidence = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({ limit: '50' });
      if (taskFilter.trim()) params.set('task_id', taskFilter.trim());

      const res = await apiFetch(`/api/v1/swarms/evidence?${params}`);
      if (!res.ok) {
        setError('Failed to fetch deployment evidence');
        setRecords([]);
        setSelected(null);
        return;
      }

      const data = (await res.json()) as DeploymentEvidenceListResponse;
      setRecords(data.evidence_records ?? []);
      setTotal(data.total ?? 0);
      setSelected((current) => {
        if (current && data.evidence_records.some((r) => r.id === current.id)) {
          return current;
        }
        return data.evidence_records[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed');
      setRecords([]);
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }, [taskFilter]);

  const fetchDetail = useCallback(async (record: DeploymentEvidenceRecord) => {
    setSelected(record);
    setDetailLoading(true);

    try {
      const res = await apiFetch(`/api/v1/swarms/evidence/${record.id}`);
      if (res.ok) {
        setSelected((await res.json()) as DeploymentEvidenceRecord);
      }
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchEvidence();
  }, [fetchEvidence]);

  const selectedJson = useMemo(
    () => (selected ? JSON.stringify(selected.evidence, null, 2) : ''),
    [selected],
  );

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
          Deployment Evidence
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          Tenant-scoped evidence records from swarm deployment tasks
        </p>
      </header>

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <input
          value={taskFilter}
          onChange={(event) => setTaskFilter(event.target.value)}
          placeholder="Filter by task_id UUID"
          className="min-w-0 flex-1 bg-slate-800 px-3 py-2 font-mono text-xs text-slate-200 pixel-border placeholder:text-slate-600"
        />
        <button
          onClick={() => void fetchEvidence()}
          className="bg-indigo-600 px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider text-white pixel-border hover:bg-indigo-500"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 bg-red-900/30 px-4 py-3 font-mono text-sm text-red-400 pixel-border">
          {error}
        </div>
      )}

      {loading ? (
        <p className="py-20 text-center font-mono text-sm text-slate-500 animate-pulse">
          Loading deployment evidence...
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,480px)]">
          <section className="min-w-0 bg-slate-800/50 pixel-border">
            <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
              <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-white">
                Evidence Records
              </h2>
              <span className="font-mono text-xs text-slate-500">
                {records.length} / {total}
              </span>
            </div>

            {records.length === 0 ? (
              <p className="px-4 py-12 text-center font-mono text-sm text-slate-600">
                No deployment evidence records found
              </p>
            ) : (
              <div className="divide-y divide-slate-800">
                {records.map((record) => (
                  <button
                    key={record.id}
                    onClick={() => void fetchDetail(record)}
                    className={`block w-full px-4 py-3 text-left transition-colors hover:bg-slate-800 ${
                      selected?.id === record.id ? 'bg-slate-800' : ''
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-cyan-400">
                        {record.task_id}
                      </span>
                      <span className="rounded bg-slate-900 px-2 py-0.5 font-mono text-[10px] uppercase text-indigo-400">
                        {record.graph_type}
                      </span>
                      <span
                        className={`border px-2 py-0.5 font-mono text-[10px] uppercase ${statusClass(
                          record.deployment_status,
                        )}`}
                      >
                        {record.deployment_status}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-slate-500">
                      {formatDate(record.created_at)}
                    </p>
                    <div className="mt-2 font-mono">
                      <EvidencePhaseSummary evidence={record.evidence} />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <aside className="min-w-0 bg-slate-800/50 pixel-border">
            <div className="border-b border-slate-700 px-4 py-3">
              <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-white">
                Evidence Detail
              </h2>
              {detailLoading && (
                <p className="mt-1 font-mono text-[10px] text-slate-500">
                  Loading detail...
                </p>
              )}
            </div>

            {selected ? (
              <div className="space-y-4 p-4">
                <dl className="grid gap-3 font-mono text-xs">
                  <div>
                    <dt className="text-[10px] uppercase text-slate-500">
                      Task ID
                    </dt>
                    <dd className="break-all text-cyan-400">
                      {selected.task_id}
                    </dd>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <dt className="text-[10px] uppercase text-slate-500">
                        Status
                      </dt>
                      <dd className="text-slate-200">
                        {selected.deployment_status}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[10px] uppercase text-slate-500">
                        Graph
                      </dt>
                      <dd className="text-slate-200">{selected.graph_type}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] uppercase text-slate-500">
                        Created
                      </dt>
                      <dd className="text-slate-200">
                        {formatDate(selected.created_at)}
                      </dd>
                    </div>
                  </div>
                </dl>

                <div>
                  <h3 className="mb-2 font-mono text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Phase Summary
                  </h3>
                  <EvidencePhaseSummary evidence={selected.evidence} />
                </div>

                <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-300">
                  {selectedJson}
                </pre>
              </div>
            ) : (
              <p className="px-4 py-12 text-center font-mono text-sm text-slate-600">
                Select an evidence record
              </p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
