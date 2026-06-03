'use client';

import { lazy, Suspense } from 'react';

/**
 * Public entry point. Lazy-loaded so the easter egg never blocks
 * first paint. Bundle target: <10KB gzipped — verify with
 * `pnpm --filter @selva/office-ui build && du -h .next/static/chunks/easter-eggs*`.
 */
const JumanjiDeviceImpl = lazy(() =>
  import('./JumanjiDeviceImpl').then((m) => ({ default: m.JumanjiDeviceImpl })),
);

export interface JumanjiDeviceProps {
  /** PostHog distinct_id or auth user_id when known. */
  userId?: string | null;
  /** Tenant org_id. */
  orgId?: string | null;
  /** Where the device renders — used in analytics. */
  currentPage: string;
  /**
   * Visual placement preset. `inline` flows in a row; `corner` is a
   * fixed bottom-right anchor. Default: `inline`.
   */
  placement?: 'inline' | 'corner';
}

export function JumanjiDevice(props: JumanjiDeviceProps) {
  return (
    <Suspense fallback={null}>
      <JumanjiDeviceImpl {...props} />
    </Suspense>
  );
}

// Re-export for stories + tests
export { JumanjiDeviceImpl } from './JumanjiDeviceImpl';
