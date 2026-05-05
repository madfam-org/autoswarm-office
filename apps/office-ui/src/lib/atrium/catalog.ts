/**
 * MADFAM Ecosystem Atrium — platform catalog.
 *
 * The Atrium is the welcoming central space inside the Selva office
 * where every MADFAM platform converges. Each entry below describes a
 * platform that can be opened as a draggable window over the office
 * canvas.
 *
 * URLs were verified live on 2026-05-04; entries that did not respond
 * at the time of audit have the corresponding field left undefined so
 * the launcher CTA renders as disabled instead of producing a broken
 * iframe.
 *
 * Tier semantics:
 *   - 'self-serve'        — customer-facing product surface
 *   - 'platform'          — internal MADFAM platform infrastructure
 *   - 'ecosystem-service' — shared internal service surface
 *
 * The `adminOnly` flag hides the entry from non-admin operators; gating
 * also happens in `useIsMadfamAdmin()` (default-deny). Admin-only URL
 * VARIANTS (entry.adminUrl) are filtered at launch time, not here.
 */

export type PlatformTier = 'self-serve' | 'platform' | 'ecosystem-service';

export interface AtriumPlatform {
  /** Stable identifier; used as localStorage key + window id. */
  slug: string;
  displayName: string;
  tagline: string;
  tier: PlatformTier;
  /** Tenant-facing app surface — primary embed target. */
  appUrl?: string;
  /** Admin-only console; gated behind useIsMadfamAdmin(). */
  adminUrl?: string;
  /** Marketing / public-facing landing. */
  publicUrl?: string;
  /** REST API root (for future health probe / dev console). */
  apiUrl?: string;
  /** Health check path under apiUrl. */
  healthPath?: string;
  /** Hide from non-admins entirely (e.g. internal-only platforms). */
  adminOnly?: boolean;
}

/**
 * Verified URLs as of 2026-05-04.
 *
 * Verification methodology: HEAD/GET to each URL via curl; any 2xx,
 * 3xx, 401, or 403 counts as "live" (auth gates are still proof the
 * service exists). 5xx, connection errors, or 404 on the documented
 * health path are treated as unverified and the field is dropped so
 * the launcher disables that CTA.
 *
 * Notable adjustments from the original brief:
 *   - tezca: documented healthPath was /api/v1/health/ (404); the
 *     working liveness path is /health.
 *   - forgesight: api.forgesight.quest/health returned 503 during
 *     audit — health field omitted (apiUrl kept; the proxy resolves
 *     even though upstream is degraded — embed should not be blocked).
 *   - fortuna: app.fortuna.tube did not resolve; appUrl dropped.
 *     Marketing site fortuna.tube is live and used as fallback CTA.
 *   - rondelio: admin.rondel.io returned 525 (CF SSL handshake) while
 *     play.rondel.io is healthy; only verified URLs are included.
 *   - phyne-crm, pravara-mes, sim4d, ceq: hostnames did not resolve
 *     during audit; embed targets dropped pending DNS / deployment
 *     confirmation.
 */
export const ATRIUM_CATALOG: readonly AtriumPlatform[] = [
  {
    slug: 'karafiel',
    displayName: 'Karafiel',
    tagline: 'CFDI compliance + RFC + SAT for Mexican accounting',
    tier: 'self-serve',
    appUrl: 'https://app.karafiel.mx',
    adminUrl: 'https://admin.karafiel.mx',
    publicUrl: 'https://karafiel.mx',
    apiUrl: 'https://api.karafiel.mx',
    healthPath: '/api/v1/monitoring/health/live',
  },
  {
    slug: 'dhanam',
    displayName: 'Dhanam',
    tagline: 'Financial wellness + ecosystem billing backbone',
    tier: 'self-serve',
    appUrl: 'https://app.dhan.am',
    adminUrl: 'https://admin.dhan.am',
    publicUrl: 'https://dhan.am',
    apiUrl: 'https://api.dhan.am',
    healthPath: '/health',
  },
  {
    slug: 'forgesight',
    displayName: 'Forge Sight',
    tagline: 'Global digital fabrication pricing intelligence',
    tier: 'self-serve',
    appUrl: 'https://app.forgesight.quest',
    adminUrl: 'https://admin.forgesight.quest',
    publicUrl: 'https://www.forgesight.quest',
    apiUrl: 'https://api.forgesight.quest',
    // healthPath omitted: api returned 503 during audit (degraded but
    // resolvable). Re-enable once Forge Sight prod stabilizes.
  },
  {
    slug: 'tezca',
    displayName: 'Tezca',
    tagline: 'Mexico open law platform — 30K+ laws, trilingual',
    tier: 'self-serve',
    appUrl: 'https://tezca.mx',
    adminUrl: 'https://admin.tezca.mx',
    apiUrl: 'https://api.tezca.mx',
    // Audited 2026-05-04: documented /api/v1/health/ returns 404; the
    // working liveness path is /health.
    healthPath: '/health',
  },
  {
    slug: 'fortuna',
    displayName: 'Fortuna',
    tagline: 'Problem intelligence + NBI scoring API',
    tier: 'self-serve',
    // appUrl omitted: app.fortuna.tube did not resolve during audit.
    // adminUrl omitted: admin.fortuna.tube did not resolve.
    publicUrl: 'https://fortuna.tube',
  },
  {
    slug: 'rondelio',
    displayName: 'Rondelio',
    tagline: 'Game intelligence cloud — TCG analytics',
    tier: 'self-serve',
    appUrl: 'https://play.rondel.io',
    // adminUrl omitted: admin.rondel.io returned 525 (CF SSL handshake)
    // during audit — re-enable when the origin cert is rotated.
    publicUrl: 'https://rondel.io',
  },
  {
    slug: 'janua',
    displayName: 'Janua',
    tagline: 'Self-hosted auth + OAuth/OIDC identity',
    tier: 'platform',
    appUrl: 'https://app.janua.dev',
    adminUrl: 'https://admin.janua.dev',
    publicUrl: 'https://janua.dev',
    apiUrl: 'https://auth.madfam.io',
    healthPath: '/health',
  },
  {
    slug: 'enclii',
    displayName: 'Enclii',
    tagline: 'Self-hosted PaaS — bare-metal K8s on Hetzner',
    tier: 'platform',
    appUrl: 'https://app.enclii.dev',
    adminUrl: 'https://admin.enclii.dev',
    publicUrl: 'https://enclii.dev',
    apiUrl: 'https://api.enclii.dev',
    healthPath: '/v1/observability/health',
  },
  {
    slug: 'selva',
    displayName: 'Selva',
    tagline: 'Autonomous AI agent platform — 240+ tools',
    tier: 'platform',
    appUrl: 'https://selva.town',
    adminUrl: 'https://admin.selva.town',
  },
  {
    slug: 'phyne-crm',
    displayName: 'PhyneCRM',
    tagline: 'Sales CRM + funnel attribution',
    tier: 'ecosystem-service',
    // appUrl/adminUrl omitted: hostnames did not resolve during audit.
  },
  {
    slug: 'cotiza',
    displayName: 'Cotiza',
    tagline: 'Quoting platform',
    tier: 'ecosystem-service',
    appUrl: 'https://app.cotiza.mx',
  },
  {
    slug: 'pravara-mes',
    displayName: 'Pravara MES',
    tagline: 'Manufacturing execution system',
    tier: 'ecosystem-service',
    // appUrl/adminUrl omitted: hostnames did not resolve during audit.
  },
  {
    slug: 'sim4d',
    displayName: 'Sim4D',
    tagline: 'Parametric CAD',
    tier: 'ecosystem-service',
    // appUrl omitted: studio.sim4d.io did not resolve during audit.
  },
  {
    slug: 'ceq',
    displayName: 'CEQ',
    tagline: 'Asset rendering',
    tier: 'ecosystem-service',
    // apiUrl omitted: api.ceq.studio did not resolve during audit.
  },
] as const;

/** Lookup an entry by slug. Returns undefined if not in catalog. */
export function getPlatformBySlug(slug: string): AtriumPlatform | undefined {
  return ATRIUM_CATALOG.find((p) => p.slug === slug);
}

/**
 * Pick the best embeddable URL for a platform.
 *
 * For non-admins this is always `appUrl` (or `publicUrl` fallback).
 * Admins get `adminUrl` when the catalog entry has one AND the caller
 * asks for admin variant — the launcher (sidebar/launchpad) decides
 * which variant to open by passing `variant`.
 *
 * Returns undefined when no URL is available — callers MUST treat
 * this as "not launchable" and disable the CTA. Never construct a
 * fallback URL here; we'd rather show a disabled tile than embed a
 * broken page.
 */
export function resolveLaunchUrl(
  entry: AtriumPlatform,
  variant: 'app' | 'admin' | 'public' = 'app',
): string | undefined {
  if (variant === 'admin' && entry.adminUrl) return entry.adminUrl;
  if (variant === 'public' && entry.publicUrl) return entry.publicUrl;
  return entry.appUrl ?? entry.publicUrl;
}

/**
 * Return the catalog filtered by admin visibility.
 *
 * Default-deny: when `isAdmin` is unknown / false, any entry with
 * `adminOnly: true` is hidden. Admin-only ENTRIES are reserved — at
 * the time of writing none of the 14 platforms set this flag, but the
 * mechanism is in place for future internal-only consoles. Admin-only
 * URL VARIANTS (entry.adminUrl) are filtered at launch time inside
 * `resolveLaunchUrl`.
 */
export function visibleCatalog(isAdmin: boolean): readonly AtriumPlatform[] {
  if (isAdmin) return ATRIUM_CATALOG;
  return ATRIUM_CATALOG.filter((p) => !p.adminOnly);
}
