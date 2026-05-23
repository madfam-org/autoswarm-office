'use client';

import type { ApprovalRequest } from '@autoswarm/shared-types';

function formatMxn(centavos: unknown): string {
  const n = typeof centavos === 'number' ? centavos : Number(centavos);
  if (!Number.isFinite(n)) return '—';
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    maximumFractionDigits: 0,
  }).format(n / 100);
}

export function PricingProposalDetails({ request }: { request: ApprovalRequest }) {
  const payload = request.payload || {};
  const summary = (payload.summary || {}) as Record<string, unknown>;
  const diff = (payload.diff || {}) as Record<string, unknown>;
  const changes = Array.isArray(diff.changes) ? diff.changes : [];

  return (
    <div className="space-y-2 border border-amber-500/40 bg-amber-950/30 p-3">
      <p className="font-mono text-[9px] uppercase tracking-wider text-amber-300">
        Tulana → Dhanam pricing proposal
      </p>
      <div className="grid gap-1 font-mono text-[8px] text-slate-300">
        <p>
          SKU: <span className="text-cyan-300">{String(summary.sku_slug ?? '—')}</span>
        </p>
        <p>
          Recommended: {formatMxn(summary.recommended_mxn_centavos)} → Proposed:{' '}
          {formatMxn(summary.proposed_mxn_centavos)}
        </p>
        <p>
          Confidence: {String(summary.confidence ?? '—')} · Decision:{' '}
          {String(summary.decision_action ?? '—')}
        </p>
      </div>
      {changes.length > 0 ? (
        <ul className="mt-2 max-h-32 overflow-y-auto space-y-1 font-mono text-[7px]">
          {changes.slice(0, 12).map((c, i) => {
            const row = c as Record<string, unknown>;
            return (
              <li key={i} className="text-slate-400">
                <span className="text-amber-200">{String(row.field ?? '')}</span>:{' '}
                {formatMxn(row.before_mxn_centavos)} → {formatMxn(row.after_mxn_centavos)}
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="text-[7px] text-slate-500">
        Approving calls Dhanam internal catalog apply, then notifies Tulana
        (applied / apply_failed on the recommendation handoff).
      </p>
    </div>
  );
}
