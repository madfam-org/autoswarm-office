'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

/**
 * M1.5 — real daily compute-token usage for the HUD meter.
 *
 * The HUD meter was fed hardcoded `{used:0, limit:10000}`, so a paying user
 * saw a fabricated number that never moved. This polls the real
 * `/billing/tokens` endpoint (daily_limit / used / remaining, tier-derived)
 * so the money surface is truthful and the meter actually approaches the cap.
 *
 * Disabled in demo mode (no real billing there) — pass `enabled=false`.
 */

export interface ComputeTokens {
  used: number;
  limit: number;
}

const POLL_INTERVAL_MS = 60_000;

export function useComputeTokens(enabled: boolean): ComputeTokens | undefined {
  const [tokens, setTokens] = useState<ComputeTokens | undefined>(undefined);

  useEffect(() => {
    if (!enabled) return;
    let active = true;

    async function fetchTokens() {
      try {
        const resp = await apiFetch('/api/v1/billing/tokens');
        if (!resp.ok) return;
        const data = (await resp.json()) as { used?: number; daily_limit?: number };
        if (active && typeof data.used === 'number' && typeof data.daily_limit === 'number') {
          setTokens({ used: data.used, limit: data.daily_limit });
        }
      } catch {
        /* leave prior value; the meter degrades to "unknown", never crashes */
      }
    }

    void fetchTokens();
    const id = setInterval(fetchTokens, POLL_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [enabled]);

  return tokens;
}
