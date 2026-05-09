/**
 * selva.town/status — public revenue-loop probe status.
 *
 * Server-rendered. Reads the latest probe run that the
 * `revenue-loop-probe` CronJob uploaded via
 * `POST /api/v1/probe/runs` and renders each of the six stages
 * (crm.hot_lead, drafter.first_touch, email.send, stripe.webhook,
 * dhanam.billing_event, phynd.attribution) with a coloured status
 * chip, a duration, and the structured facts each stage surfaces.
 *
 * No auth here — the probe token stays server-side and the payload
 * is deliberately safe to publish (synthetic lead, dry-run message
 * ids, no PII). If the probe hasn't uploaded a run yet, we render
 * an empty state instead of 500-ing.
 */
import type { Metadata } from 'next';
import Link from 'next/link';
import { JumanjiDevice } from '@/components/easter-eggs/JumanjiDevice';

// Refetch every 30s so the page never goes more than one cycle stale.
export const revalidate = 30;

export const metadata: Metadata = {
  title: 'Selva — Revenue Loop Status',
  description:
    'Live status of the MADFAM revenue-loop probe: CRM -> draft -> email -> Stripe -> billing -> attribution.',
};

// Matches apps/nexus-api/nexus_api/routers/probe.py::StoredProbeRun.
interface StageReport {
  name: string;
  status: 'passed' | 'failed' | 'skipped' | 'dry_run';
  duration_ms: number;
  detail: string | null;
  facts: Record<string, unknown>;
}
interface StoredProbeRun {
  correlation_id: string;
  dry_run: boolean;
  started_at: number;
  finished_at: number;
  duration_ms: number;
  ok: boolean;
  fail_count: number;
  stages: StageReport[];
  received_at: number;
}

// Ordered canonical stages — render them in this order even if the probe
// returns a subset, so the page layout stays stable.
const CANONICAL_STAGES: { key: string; label: string; description: string }[] = [
  {
    key: 'crm.hot_lead',
    label: 'CRM hot lead',
    description: 'Synthetic lead created in PhyndCRM.',
  },
  {
    key: 'drafter.first_touch',
    label: 'Draft email',
    description: 'Nexus drafter produces the first-touch message.',
  },
  {
    key: 'email.send',
    label: 'Email send contract',
    description: 'Sanitisation, list-unsubscribe header, fixed sender.',
  },
  {
    key: 'stripe.webhook',
    label: 'Stripe webhook',
    description: 'Signed synthetic payment event reaches Dhanam.',
  },
  {
    key: 'dhanam.billing_event',
    label: 'Dhanam billing event',
    description: 'Ledger row written + billing_event_id issued.',
  },
  {
    key: 'phynd.attribution',
    label: 'PhyndCRM attribution',
    description: 'Conversion bound to lead + event + source agent.',
  },
];

async function fetchLatestRun(): Promise<StoredProbeRun | null> {
  const base =
    process.env.NEXUS_API_INTERNAL_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    'http://localhost:4300';
  const url = `${base.replace(/\/$/, '')}/api/v1/probe/latest-run`;
  try {
    const res = await fetch(url, { next: { revalidate: 30 } });
    if (!res.ok) return null;
    const body = (await res.json()) as StoredProbeRun | null;
    return body ?? null;
  } catch {
    return null;
  }
}

function formatAgo(unixSec: number): string {
  const deltaSec = Math.max(0, Date.now() / 1000 - unixSec);
  if (deltaSec < 60) return `${Math.floor(deltaSec)}s ago`;
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)}m ago`;
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)}h ago`;
  return `${Math.floor(deltaSec / 86400)}d ago`;
}

function statusChip(status: StageReport['status']) {
  const base =
    'inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold';
  switch (status) {
    case 'passed':
      return `${base} bg-emerald-600/20 text-emerald-300`;
    case 'dry_run':
      return `${base} bg-cyan-600/20 text-cyan-300`;
    case 'skipped':
      return `${base} bg-slate-600/30 text-slate-300`;
    case 'failed':
      return `${base} bg-rose-600/25 text-rose-300`;
  }
}

function StageCard({
  label,
  description,
  stage,
}: {
  label: string;
  description: string;
  stage: StageReport | undefined;
}) {
  const status: StageReport['status'] = stage?.status ?? 'skipped';
  const durationMs = stage?.duration_ms ?? 0;
  const factEntries = stage?.facts ? Object.entries(stage.facts) : [];
  return (
    <li className="pixel-border-accent rounded-sm bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="pixel-text text-xs text-white">{label}</h3>
        <span className={statusChip(status)}>{status}</span>
      </div>
      <p className="mb-3 text-xs leading-relaxed text-slate-400">{description}</p>
      <div className="flex items-center justify-between text-[11px] text-slate-500">
        <span>{durationMs ? `${Math.round(durationMs)}ms` : '—'}</span>
        {stage?.detail ? (
          <span className="truncate text-rose-300" title={stage.detail}>
            {stage.detail.slice(0, 60)}
          </span>
        ) : null}
      </div>
      {factEntries.length > 0 ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-400">
          {factEntries.slice(0, 6).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="truncate text-slate-500">{k}</dt>
              <dd className="truncate text-slate-300">{String(v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}

function OverallBadge({ run }: { run: StoredProbeRun }) {
  const color = run.ok
    ? 'border-emerald-500/40 bg-emerald-600/15 text-emerald-300'
    : 'border-rose-500/40 bg-rose-600/15 text-rose-300';
  const label = run.ok ? 'Loop healthy' : `${run.fail_count} stage(s) failing`;
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-sm border px-3 py-1 text-xs font-semibold uppercase tracking-wider ${color}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${run.ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
      {label}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-xl rounded-sm border border-slate-700/60 bg-slate-900/40 p-8 text-center">
      <h2 className="pixel-text mb-3 text-sm text-amber-300">No probe run recorded yet</h2>
      <p className="text-sm leading-relaxed text-slate-400">
        The revenue-loop probe runs hourly as a Kubernetes CronJob. Once the
        next cycle uploads its report, this page will light up with the
        end-to-end health of the MADFAM loop.
      </p>
      <p className="mt-4 text-xs text-slate-500">
        Deploy notes: set <code>NEXUS_API_URL</code> and{' '}
        <code>NEXUS_PROBE_TOKEN</code> in the probe&rsquo;s CronJob secret.
      </p>
    </div>
  );
}

export default async function StatusPage() {
  const run = await fetchLatestRun();

  return (
    <div className="min-h-screen bg-slate-950 scanline-overlay">
      <main className="mx-auto max-w-5xl px-4 py-16">
        <div className="mb-10">
          <div className="mb-3 flex items-center gap-3 text-xs text-slate-500">
            <Link href="/" className="hover:text-emerald-400">
              ← selva.town
            </Link>
            <span>/</span>
            <span className="text-slate-400">status</span>
            <span className="ml-auto flex gap-3">
              <Link href="/atrium" className="text-slate-500 hover:text-emerald-400">
                Atrium →
              </Link>
              <Link href="/catalog" className="text-slate-500 hover:text-emerald-400">
                catalog →
              </Link>
              <Link href="/bundles" className="text-slate-500 hover:text-emerald-400">
                bundles →
              </Link>
            </span>
          </div>
          <h1 className="pixel-text mb-3 text-lg text-emerald-400">
            Revenue-loop probe status
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-slate-400">
            Hourly synthetic run of the MADFAM revenue flywheel: PhyndCRM lead{' '}
            → Nexus drafter → email send contract → Dhanam Stripe webhook → billing
            event → PhyndCRM attribution. Every stage is dry-run by design —
            no real customer ever sees this traffic.
          </p>
        </div>

        {run ? (
          <>
            <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
              <OverallBadge run={run} />
              <div className="text-[11px] text-slate-500">
                Last run {formatAgo(run.received_at)} · correlation{' '}
                <code className="text-slate-400">{run.correlation_id}</code> · {run.dry_run ? 'dry-run' : 'LIVE'}
              </div>
            </div>

            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {CANONICAL_STAGES.map(({ key, label, description }) => {
                const stage = run.stages.find((s) => s.name === key);
                return (
                  <StageCard
                    key={key}
                    label={label}
                    description={description}
                    stage={stage}
                  />
                );
              })}
            </ul>

            <div className="mt-10 flex items-center justify-center gap-4 text-[11px] text-slate-600">
              <span>Page revalidates every 30s. Probe runs every hour at :07.</span>
              {/*
                Easter egg placement: tucked into the status footer so the
                device "looks like" another tiny system component
                (orchestrator/router/redis row context). Not on a
                high-traffic CTA page.
              */}
              <JumanjiDevice currentPage="/status" placement="inline" />
            </div>
          </>
        ) : (
          <div className="space-y-12">
            <EmptyState />
            <div className="flex items-center justify-center gap-4 text-[11px] text-slate-600">
              <span>Awaiting first probe upload.</span>
              <JumanjiDevice currentPage="/status" placement="inline" />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
