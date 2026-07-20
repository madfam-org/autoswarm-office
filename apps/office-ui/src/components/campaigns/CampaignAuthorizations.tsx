'use client';

import { useCallback, useEffect, useState, type FC } from 'react';

import {
  decideAuthorization,
  getAuthorizationPreview,
  listPendingAuthorizations,
  requestFreshAuthorization,
} from '@/components/campaigns/api';
import type {
  AuthorizationConsentCoverage,
  AuthorizationPreview,
  PendingAuthorizationRow,
} from '@/components/campaigns/types';
import { useToast } from '@/hooks/useToast';

/**
 * Owner money-gate surface inside Selva. PhyndCRM owns the
 * ``campaign_authorizations`` ledger and the fail-closed send gate; this
 * panel only READS the pending queue / full review and RELAYS the owner's
 * authorize/reject decision through nexus-api → phynd. Every decision is
 * recorded in phynd's immutable ledger as ``"<operator> (via service:selva)"``.
 */

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('es-MX', { dateStyle: 'medium' });
  } catch {
    return iso;
  }
}

function fmtNum(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('es-MX');
}

function CoverageGrid({ coverage }: { coverage: AuthorizationConsentCoverage }) {
  const rows: [string, number, boolean?][] = [
    ['Contacts with email', coverage.contactsWithEmail],
    ['Consent granted', coverage.consent.granted],
    ['Pending double opt-in', coverage.consent.pendingDoubleOptIn],
    ['Consent revoked', coverage.consent.revoked],
    ['Suppressed', coverage.suppressed],
    ['Sendable today', coverage.grantedNotSuppressed, true],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
      {rows.map(([label, value, emphasis]) => (
        <div
          key={label}
          className={`flex items-baseline justify-between gap-2 ${
            emphasis ? 'col-span-2 border-t border-slate-700 pt-1 mt-1' : ''
          }`}
        >
          <dt className={`font-mono text-[8px] ${emphasis ? 'text-emerald-300' : 'text-slate-500'}`}>
            {label}
          </dt>
          <dd
            className={`font-mono tabular-nums ${
              emphasis ? 'text-[11px] text-emerald-300' : 'text-[9px] text-slate-200'
            }`}
          >
            {fmtNum(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export const CampaignAuthorizations: FC = () => {
  const { addToast } = useToast();
  const [pending, setPending] = useState<PendingAuthorizationRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preview, setPreview] = useState<AuthorizationPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const loadPending = useCallback(async () => {
    setLoadError(null);
    try {
      setPending(await listPendingAuthorizations());
    } catch (err) {
      setPending([]);
      setLoadError(err instanceof Error ? err.message : 'Failed to load pending authorizations');
    }
  }, []);

  useEffect(() => {
    void loadPending();
  }, [loadPending]);

  const openPreview = useCallback(
    async (authorizationId: string) => {
      setSelectedId(authorizationId);
      setPreview(null);
      setNote('');
      setPreviewLoading(true);
      try {
        setPreview(await getAuthorizationPreview(authorizationId));
      } catch (err) {
        addToast(err instanceof Error ? err.message : 'Failed to load review', 'error');
        setSelectedId(null);
      } finally {
        setPreviewLoading(false);
      }
    },
    [addToast],
  );

  const closePreview = useCallback(() => {
    setSelectedId(null);
    setPreview(null);
    setNote('');
  }, []);

  const decide = useCallback(
    async (decision: 'authorized' | 'rejected') => {
      if (!preview) return;
      const trimmed = note.trim();
      if (decision === 'rejected' && !trimmed) {
        addToast('A written reason is required to reject', 'warning');
        return;
      }
      setBusy(true);
      try {
        await decideAuthorization(preview.authorization.id, decision, trimmed || undefined);
        addToast(
          decision === 'authorized'
            ? 'Campaign authorized for send'
            : 'Campaign rejected — the send path stays blocked',
          decision === 'authorized' ? 'success' : 'warning',
        );
        closePreview();
        await loadPending();
      } catch (err) {
        addToast(err instanceof Error ? err.message : 'Decision failed', 'error');
      } finally {
        setBusy(false);
      }
    },
    [preview, note, addToast, closePreview, loadPending],
  );

  const requestFresh = useCallback(
    async (campaignId: string) => {
      setBusy(true);
      try {
        const record = await requestFreshAuthorization(campaignId);
        addToast('Fresh authorization request created from current content', 'success');
        await loadPending();
        if (record.id) await openPreview(record.id);
      } catch (err) {
        addToast(err instanceof Error ? err.message : 'Could not create request', 'error');
      } finally {
        setBusy(false);
      }
    },
    [addToast, loadPending, openPreview],
  );

  // ---- Detail review view -------------------------------------------------
  if (selectedId) {
    if (previewLoading || !preview) {
      return (
        <p className="font-mono text-[9px] text-slate-500">Loading review…</p>
      );
    }
    const { authorization, snapshot, stale } = preview;
    const { payload, context } = snapshot;
    return (
      <div className="space-y-3 max-w-4xl">
        <button
          type="button"
          onClick={closePreview}
          className="font-mono text-[8px] uppercase text-slate-400 hover:text-white"
        >
          ← Back to queue
        </button>

        <div>
          <h3 className="pixel-text text-[10px] uppercase text-indigo-300">{payload.name}</h3>
          <p className="font-mono text-[8px] text-slate-500 mt-1">
            {payload.skuKey ?? 'no sku'} · requested by {authorization.requestedBy} ·{' '}
            {fmtDateTime(context.capturedAt)}
          </p>
        </div>

        {stale && (
          <div className="rounded border border-amber-700 bg-amber-950/30 px-3 py-2 font-mono text-[8px] text-amber-200">
            The campaign changed after this snapshot was taken — it can no longer be authorized as
            reviewed. Create a fresh review of the current content.
            <div className="mt-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void requestFresh(authorization.campaignId)}
                className="rounded bg-indigo-600 px-3 py-1 font-mono text-[8px] text-white retro-btn disabled:opacity-50"
              >
                {busy ? 'Working…' : 'Request fresh review'}
              </button>
            </div>
          </div>
        )}

        <div className="grid gap-3 lg:grid-cols-2">
          {/* What is being authorized */}
          <div className="retro-panel p-3 space-y-2">
            <h4 className="pixel-text text-[8px] uppercase text-slate-500">What you are authorizing</h4>
            <dl className="space-y-1.5 font-mono text-[9px]">
              <div>
                <dt className="text-[8px] uppercase text-slate-500">Sender</dt>
                <dd className="text-slate-200">{payload.sender}</dd>
              </div>
              <div>
                <dt className="text-[8px] uppercase text-slate-500">Channel</dt>
                <dd className="text-slate-200">{payload.channel}</dd>
              </div>
              <div>
                <dt className="text-[8px] uppercase text-slate-500">Send window</dt>
                <dd className="text-slate-200">
                  {payload.schedule.startDate || payload.schedule.endDate
                    ? `${fmtDate(payload.schedule.startDate)} – ${fmtDate(payload.schedule.endDate)}`
                    : 'Not scheduled'}
                </dd>
              </div>
              <div>
                <dt className="text-[8px] uppercase text-slate-500">Audience</dt>
                <dd className="text-slate-300">
                  {payload.audienceDefinition ?? 'Not defined on the import'}
                </dd>
              </div>
              {payload.privacyUrl && (
                <div>
                  <dt className="text-[8px] uppercase text-slate-500">Aviso de Privacidad</dt>
                  <dd className="text-slate-300 break-all">{payload.privacyUrl}</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Consent coverage */}
          <div className="retro-panel p-3 space-y-2">
            <h4 className="pixel-text text-[8px] uppercase text-slate-500">
              Consent coverage at snapshot
            </h4>
            <CoverageGrid coverage={context.coverage} />
            <p className="font-mono text-[7px] text-slate-500">
              Real ledger counts. Every contact is re-checked against consent and suppression at
              send time; suppression always wins.
            </p>
          </div>
        </div>

        {payload.guardrailsDoNotClaim.length > 0 && (
          <div className="rounded border border-amber-800/60 bg-amber-950/20 p-3">
            <h4 className="pixel-text text-[8px] uppercase text-amber-300">Guardrails — never claim</h4>
            <ul className="mt-1.5 list-disc space-y-1 pl-4 font-mono text-[8px] text-amber-200/90">
              {payload.guardrailsDoNotClaim.map((claim) => (
                <li key={claim}>{claim}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Copy variants */}
        <div className="space-y-2">
          <h4 className="pixel-text text-[8px] uppercase text-slate-500">
            Copy variants ({payload.variants.length}) — exactly what ships
          </h4>
          {payload.variants.map((variant, i) => (
            <div key={variant.variantId ?? i} className="retro-panel p-3 space-y-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[9px] text-slate-200">
                  {variant.variantId ?? `Variant ${i + 1}`}
                </span>
                {variant.language && (
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[7px] text-slate-400 border border-slate-700">
                    {variant.language}
                  </span>
                )}
                {variant.claimKeysUsed.map((key) => (
                  <span
                    key={key}
                    className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[7px] text-slate-500 border border-slate-700"
                  >
                    {key}
                  </span>
                ))}
              </div>
              <p className="font-mono text-[9px] text-slate-200">
                <span className="text-slate-500">Subject: </span>
                {variant.subject ?? '—'}
              </p>
              {variant.preheader && (
                <p className="font-mono text-[8px] text-slate-400">
                  <span className="text-slate-500">Preheader: </span>
                  {variant.preheader}
                </p>
              )}
              <pre className="whitespace-pre-wrap font-mono text-[8px] leading-relaxed text-slate-300 max-h-64 overflow-y-auto rounded bg-slate-900/60 p-2">
                {variant.body}
              </pre>
              {variant.cta && (
                <p className="font-mono text-[8px] text-cyan-300">
                  CTA: {variant.cta}
                  {variant.ctaUrl ? ` → ${variant.ctaUrl}` : ''}
                </p>
              )}
            </div>
          ))}
        </div>

        {/* Decision */}
        {authorization.status === 'pending' && !stale ? (
          <div className="retro-panel p-3 space-y-2">
            <h4 className="pixel-text text-[8px] uppercase text-slate-500">Your decision</h4>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="Optional note when authorizing · required reason when rejecting"
              className="w-full resize-y rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 font-mono text-[9px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide('authorized')}
                className="rounded bg-emerald-700 px-4 py-1.5 font-mono text-[9px] text-white retro-btn hover:bg-emerald-600 disabled:opacity-50"
              >
                {busy ? 'Recording…' : 'Authorize send'}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide('rejected')}
                className="rounded bg-red-800 px-4 py-1.5 font-mono text-[9px] text-white retro-btn hover:bg-red-700 disabled:opacity-50"
              >
                Reject
              </button>
            </div>
            <p className="font-mono text-[7px] text-slate-500">
              Your operator identity, the timestamp, and this exact snapshot are recorded in
              phynd&apos;s immutable ledger. Any later edit to the campaign voids the authorization
              automatically.
            </p>
          </div>
        ) : (
          <div className="retro-panel p-3 font-mono text-[8px] text-slate-400">
            Decision: <span className="text-slate-200">{authorization.status}</span>
            {authorization.decidedBy ? ` · by ${authorization.decidedBy}` : ''}
            {authorization.decidedAt ? ` · ${fmtDateTime(authorization.decidedAt)}` : ''}
          </div>
        )}
      </div>
    );
  }

  // ---- Queue list view ----------------------------------------------------
  return (
    <div className="space-y-3 max-w-3xl">
      <p className="font-mono text-[9px] text-slate-400">
        The owner money-gate: no campaign can send without your explicit authorization of its exact
        content, audience, and schedule. PhyndCRM is the source of truth and the fail-closed send
        gate.
      </p>

      {loadError && (
        <p className="rounded border border-red-800 bg-red-950/40 px-3 py-2 font-mono text-[9px] text-red-300">
          {loadError}
        </p>
      )}

      {pending === null ? (
        <p className="font-mono text-[9px] text-slate-500">Loading pending authorizations…</p>
      ) : pending.length === 0 ? (
        <p className="font-mono text-[9px] text-slate-500 italic">
          No campaigns are waiting for authorization.
        </p>
      ) : (
        pending.map(({ authorization, campaign }) => {
          const coverage = authorization.snapshot?.context?.coverage;
          const variantCount = authorization.snapshot?.payload?.variants?.length ?? 0;
          return (
            <div
              key={authorization.id}
              className="retro-panel p-3 border-l-2 border-emerald-500 space-y-2 animate-fade-in-up"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <span className="pixel-text text-[9px] text-emerald-300">{campaign.name}</span>
                  <p className="font-mono text-[8px] text-slate-500 mt-1">
                    {campaign.skuKey ?? 'no sku'} · {variantCount} variant
                    {variantCount === 1 ? '' : 's'} · requested {fmtDateTime(authorization.createdAt)}
                  </p>
                </div>
                <span className="rounded bg-amber-900/50 px-1.5 py-0.5 font-mono text-[7px] uppercase text-amber-300 border border-amber-800">
                  pending
                </span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[8px] text-slate-400">
                <span>
                  Sendable today:{' '}
                  <span className="text-slate-200">
                    {fmtNum(coverage?.grantedNotSuppressed)} of {fmtNum(coverage?.contactsWithEmail)}
                  </span>
                  {' · '}
                  {campaign.startDate || campaign.endDate
                    ? `${fmtDate(campaign.startDate)} – ${fmtDate(campaign.endDate)}`
                    : 'Not scheduled'}
                </span>
                <button
                  type="button"
                  onClick={() => void openPreview(authorization.id)}
                  className="rounded bg-indigo-600 px-3 py-1 font-mono text-[8px] text-white retro-btn hover:bg-indigo-500"
                >
                  Review →
                </button>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
};
