/**
 * Entitlements store — caches the operator's MADFAM ecosystem grants.
 *
 * Sourced from `GET /api/v1/me/entitlements` on the Janua API. Phase 1 of
 * the Selva-unified SSO design (see internal-devops/decisions/2026-05-04-
 * selva-unified-sso.md): the Atrium uses this store to gate catalog tiles
 * BEFORE rendering the iframe. Tiles for products the operator isn't
 * entitled to under their current plan render in a "needs upgrade" state
 * that links to the Dhanam pricing page rather than embedding the app.
 *
 * Design notes:
 *
 * - Store is in-memory only — NOT persisted to localStorage. The JWT
 *   already carries the same data in the `madfam_entitled_products`
 *   claim; persisting on the client would let stale entitlements survive
 *   across logouts. Phase 2 SSE will keep this fresh; Phase 1 polls on
 *   `/atrium` mount.
 *
 * - Status state machine: `idle → loading → ready` on success,
 *   `idle → loading → error` on failure. Components render skeletons
 *   when `loading`, the gated UI when `ready`, and a fail-open default
 *   (treat user as entitled to everything) when `error` so a flaky
 *   Janua does not strand operators behind upgrade walls. The fail-open
 *   choice is documented in the ADR § Threat model.
 *
 * - `entitledSlugs` is a Set for O(1) lookup; `tierBySlug` is a Record
 *   for tile rendering when we need to surface the user's current tier
 *   (e.g. "Currently on: Contador").
 *
 * - Admin grants flow through transparently. A user with
 *   `karafiel:admin` in their JWT will have `tierBySlug.karafiel === 'admin'`.
 *   No special-casing needed in the store — the gating logic in the
 *   launchpad uses `isEntitled(slug)` which is true for ANY tier.
 */

import { create } from 'zustand';

export type EntitlementsStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface EntitlementResponse {
  /** Product slug — matches `AtriumPlatform.slug` in the catalog. */
  slug: string;
  /** Tier within the product (e.g. 'contador', 'pro', 'admin'). */
  tier: string;
  /** ISO-8601 timestamp or null. */
  expires_at: string | null;
  /** 'dhanam_subscription' | 'admin_grant' | 'inherited'. */
  source: string;
}

export interface EntitlementsApiResponse {
  products: EntitlementResponse[];
  /** Mirrors the JWT claim shape — array of `<slug>:<tier>` strings. */
  claim_string_form: string[];
}

interface EntitlementsStoreState {
  status: EntitlementsStatus;
  /** Set of product slugs the user is entitled to at any tier. */
  entitledSlugs: Set<string>;
  /** Per-slug tier (e.g. 'pro'); undefined when not entitled. */
  tierBySlug: Record<string, string>;
  /** Last-fetch error message — surfaced in dev / debug. */
  errorMessage: string | null;
  /** When the last successful fetch completed. */
  fetchedAt: number | null;

  /** Trigger a fetch. Idempotent while a fetch is already in flight. */
  fetch: (apiBaseUrl?: string) => Promise<void>;
  /** Synchronous lookup — true iff the user has any tier of the slug. */
  isEntitled: (slug: string) => boolean;
  /** Returns the current tier for a slug or undefined when not entitled. */
  tierFor: (slug: string) => string | undefined;
  /** Test-only reset. */
  _reset: () => void;
  /** Test/dev hook to seed the store without an HTTP fetch. */
  _hydrate: (response: EntitlementsApiResponse) => void;
}

const DEFAULT_API_BASE_URL =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (typeof process !== 'undefined' ? (process as any).env?.NEXT_PUBLIC_JANUA_API_URL : undefined) ??
  'https://auth.madfam.io';

function resolveApiBaseUrl(override?: string): string {
  return override ?? DEFAULT_API_BASE_URL;
}

/**
 * Read the Janua session cookie. The Atrium runs on `*.selva.town`; the
 * cookie domain is `.madfam.io` for the SSO session and `.selva.town`
 * for the Selva session. Both share the JWT shape, but only the Janua
 * cookie is accepted by `auth.madfam.io`. We try `janua-session` first
 * (the cookie name shipped today) and fall back to `janua_access_token`
 * (the cookie name set by the Janua login form).
 */
function getJanuaSessionToken(): string | null {
  if (typeof document === 'undefined') return null;
  const cookieString = document.cookie;
  const candidates = ['janua-session', 'janua_access_token'];
  for (const name of candidates) {
    const match = cookieString.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
    if (match) return match[1];
  }
  return null;
}

export const useEntitlementsStore = create<EntitlementsStoreState>((set, get) => ({
  status: 'idle',
  entitledSlugs: new Set<string>(),
  tierBySlug: {},
  errorMessage: null,
  fetchedAt: null,

  isEntitled: (slug) => get().entitledSlugs.has(slug),
  tierFor: (slug) => get().tierBySlug[slug],

  async fetch(apiBaseUrl) {
    // Idempotent: don't kick off a second fetch while one is already
    // running. The hook should call this on mount once per session.
    if (get().status === 'loading') return;

    set({ status: 'loading', errorMessage: null });

    const url = `${resolveApiBaseUrl(apiBaseUrl).replace(/\/+$/, '')}/api/v1/me/entitlements`;
    const token = getJanuaSessionToken();

    try {
      const headers: Record<string, string> = {
        Accept: 'application/json',
      };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(url, {
        headers,
        // Cookies are scoped to madfam.io; we still send credentials so
        // the SameSite=Lax cookie travels even when the Bearer header is
        // absent (e.g. when Atrium runs same-origin in dev).
        credentials: 'include',
      });

      if (!response.ok) {
        // Don't strand the user when Janua returns 401: just fail open.
        // The ADR § Threat model accepts this — UI gating is best-effort,
        // platform services re-validate authorization on every call.
        if (response.status === 401) {
          set({
            status: 'error',
            errorMessage: 'unauthenticated',
          });
          return;
        }
        throw new Error(`HTTP ${response.status}`);
      }

      const body: EntitlementsApiResponse = await response.json();
      const slugs = new Set<string>();
      const tiers: Record<string, string> = {};
      for (const row of body.products) {
        slugs.add(row.slug);
        tiers[row.slug] = row.tier;
      }

      set({
        status: 'ready',
        entitledSlugs: slugs,
        tierBySlug: tiers,
        errorMessage: null,
        fetchedAt: Date.now(),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ status: 'error', errorMessage: msg });
    }
  },

  _reset() {
    set({
      status: 'idle',
      entitledSlugs: new Set<string>(),
      tierBySlug: {},
      errorMessage: null,
      fetchedAt: null,
    });
  },

  _hydrate(response) {
    const slugs = new Set<string>();
    const tiers: Record<string, string> = {};
    for (const row of response.products) {
      slugs.add(row.slug);
      tiers[row.slug] = row.tier;
    }
    set({
      status: 'ready',
      entitledSlugs: slugs,
      tierBySlug: tiers,
      errorMessage: null,
      fetchedAt: Date.now(),
    });
  },
}));

/**
 * Selector: should the launcher gate this slug?
 *
 * Returns `true` when the entitlements store is ready AND the slug is
 * absent. Returns `false` (don't gate) while the store is loading, in
 * error state, or when the slug is present.
 *
 * Fail-open behaviour: a 401 / network error from Janua leaves the
 * store in `error` and this selector returns `false` for every slug.
 * The user sees an unrestricted Atrium, exactly like before this PR.
 * Real authorization is enforced at the target platform on every API
 * call — UI gating is courtesy, not security.
 */
export function shouldGateSlug(
  slug: string,
  state: Pick<EntitlementsStoreState, 'status' | 'entitledSlugs'>,
): boolean {
  if (state.status !== 'ready') return false;
  return !state.entitledSlugs.has(slug);
}
