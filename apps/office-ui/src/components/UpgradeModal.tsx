'use client';

import { useEffect, useRef } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useCheckout } from '@/hooks/useCheckout';

/**
 * The upgrade moment (M2). Shown when a dispatch is refused for hitting the
 * plan's compute budget (HTTP 402 `budget_exhausted`) — the highest-intent
 * conversion point in the product: the user hit a wall mid-value.
 *
 * Offers one-click checkout to the next tier (reusing the M1 useCheckout
 * flow) plus a link to the full pricing page.
 */

interface UpgradeModalProps {
  open: boolean;
  onClose: () => void;
  /** Human message from the 402 (falls back to a generic line). */
  message?: string | null;
  /** Tier to upgrade to on the one-click CTA. */
  suggestedTier?: string;
}

export function UpgradeModal({
  open,
  onClose,
  message,
  suggestedTier = 'professional',
}: UpgradeModalProps) {
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const { loading, startCheckout } = useCheckout();

  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="upgrade-modal-title"
    >
      <div
        ref={trapRef}
        className="w-full max-w-md rounded-2xl border border-edge bg-surface-raised p-6 shadow-lg"
      >
        <div className="mb-2 flex items-start justify-between gap-4">
          <h2 id="upgrade-modal-title" className="text-lg font-semibold text-ink">
            You&apos;ve hit today&apos;s limit
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="rounded p-1 text-ink-muted hover:text-ink"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <p className="mb-6 text-sm text-ink-muted">
          {message ??
            'Your agents have used up your plan’s compute budget for today. Upgrade for a higher daily limit and keep them working.'}
        </p>

        <button
          type="button"
          onClick={() => startCheckout(suggestedTier)}
          disabled={loading}
          className="w-full rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {loading ? 'Starting checkout…' : 'Upgrade my plan'}
        </button>

        <a
          href="/pricing"
          className="mt-3 block text-center text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
        >
          See all plans
        </a>
      </div>
    </div>
  );
}
