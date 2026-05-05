'use client';

/**
 * useEntitlements — single-responsibility hook that triggers a fetch of
 * the operator's MADFAM entitlements when the Atrium mounts.
 *
 * Idempotent: the underlying store rejects concurrent fetches, and the
 * effect runs once per Atrium mount. Re-mounts (e.g. SPA route change)
 * re-poll, which is the simplest implementation path for Phase 1 — the
 * ADR § Phase 2 swaps this for a Server-Sent Events stream so changes
 * to a user's plan reach the UI without a re-mount.
 */

import { useEffect } from 'react';
import { useEntitlementsStore } from '@/stores/entitlements';

export function useEntitlements(): void {
  const fetchEntitlements = useEntitlementsStore((s) => s.fetch);
  const status = useEntitlementsStore((s) => s.status);

  useEffect(() => {
    // Skip when we already have data or a fetch is in flight.
    if (status === 'ready' || status === 'loading') return;
    void fetchEntitlements();
    // We intentionally depend only on `status` — `fetchEntitlements` is
    // a stable Zustand action ref. Status transitions monotonically through
    // this effect's lifetime.
  }, [status, fetchEntitlements]);
}
