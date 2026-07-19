'use client';

import { useCallback, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useToast } from '@/hooks/useToast';

/**
 * M1 "First Peso" — start a subscription checkout.
 *
 * Selva holds no Stripe keys: this asks nexus-api (which asks Dhanam) to
 * create a hosted checkout, then redirects the browser to it. Until Dhanam's
 * checkout API is live the backend returns 501 `not_configured`, which we
 * surface as a truthful "not available yet" toast rather than a hard error —
 * the same call flips to a real redirect the moment Dhanam ships.
 */

interface CheckoutState {
  /** True while a checkout request is in flight (disable the buy button). */
  loading: boolean;
  /** Start checkout for a tier slug. Redirects on success. */
  startCheckout: (tier: string) => Promise<void>;
}

export function useCheckout(): CheckoutState {
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  const startCheckout = useCallback(
    async (tier: string) => {
      setLoading(true);
      try {
        const resp = await apiFetch('/api/v1/billing/checkout', {
          method: 'POST',
          body: JSON.stringify({ tier }),
        });

        if (resp.status === 501) {
          // Dhanam checkout not live yet — truthful, non-alarming message.
          addToast(
            'Checkout is coming soon — self-serve upgrade is not available yet.',
            'info',
          );
          return;
        }

        if (!resp.ok) {
          addToast('Could not start checkout. Please try again.', 'error');
          return;
        }

        const data = (await resp.json()) as { url?: string };
        if (data.url) {
          window.location.href = data.url;
          return;
        }
        addToast('Checkout did not return a payment link.', 'error');
      } catch {
        addToast('Checkout is temporarily unavailable.', 'error');
      } finally {
        setLoading(false);
      }
    },
    [addToast],
  );

  return { loading, startCheckout };
}
