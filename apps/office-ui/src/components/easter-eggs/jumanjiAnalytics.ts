'use client';

import { trackEvent } from '@/lib/analytics/posthog';

/**
 * PostHog event names emitted by the Jumanji easter egg.
 * Kept as a const map so test mocks can match exactly.
 */
export const JUMANJI_EVENTS = {
  SEEN: 'jumanji_egg_seen',
  ACTIVATED: 'jumanji_egg_activated',
  PORTALED: 'jumanji_egg_portaled',
} as const;

/**
 * Base URL of the Rondelio simulator. play.rondel.io exists (HTTP 200,
 * no X-Frame-Options, no CSP frame-ancestors as of 2026-05-04 — see
 * PR body for the curl trace) so we can iframe it. If the operator
 * later locks the site down, the modal falls back to a new tab via
 * the iframe's onError handler in JumanjiPortalModal.
 */
const PORTAL_BASE_URL = 'https://play.rondel.io';

export interface JumanjiPortalUrlOptions {
  /** PostHog distinct_id or auth user_id when known. */
  userId?: string | null;
  /** Tenant org_id. */
  orgId?: string | null;
}

/**
 * Build the portal URL with UTM tracking. Stable shape so analytics
 * dashboards on rondel.io can pivot on it.
 */
export function buildPortalUrl(opts: JumanjiPortalUrlOptions = {}): string {
  const params = new URLSearchParams({
    utm_source: 'selva',
    utm_medium: 'easter_egg',
    utm_campaign: 'jumanji_device',
    utm_content: 'device_v1',
  });
  if (opts.userId) params.set('selva_uid', opts.userId);
  if (opts.orgId) params.set('selva_org', opts.orgId);
  return `${PORTAL_BASE_URL}/?${params.toString()}`;
}

export interface JumanjiEventProperties {
  user_id?: string | null;
  org_id?: string | null;
  /** ms since the page loaded. */
  discovered_at?: number;
  /** Current next.js route at the time of emission. */
  current_page?: string;
  /** Free-form variant tag (currently always "device_v1"). */
  variant?: string;
}

/**
 * Wrapper around `trackEvent` so the easter egg has one analytics
 * surface. If PostHog isn't initialized (e.g. NEXT_PUBLIC_POSTHOG_KEY
 * unset in dev), `trackEvent` is a no-op — see
 * `apps/office-ui/src/lib/analytics/posthog.ts`. There is no
 * analytics gap in this repo, so we don't stub.
 */
export function emitJumanjiEvent(
  name: (typeof JUMANJI_EVENTS)[keyof typeof JUMANJI_EVENTS],
  props: JumanjiEventProperties = {},
): void {
  trackEvent(name, {
    variant: 'device_v1',
    ...props,
  });
}
