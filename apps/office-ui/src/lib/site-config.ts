/**
 * Centralized public site URLs.
 *
 * Components MUST NOT hardcode `https://app.selva.town` or
 * `https://selva.town` directly — staging deploys would silently leak
 * prod URLs into hero CTAs, footer links, and OG tags.
 *
 * Behaviour:
 *  - In production builds with the env vars MISSING, this throws at the
 *    first call site. We prefer a build-time/render-time crash over
 *    shipping a staging build that points users at the prod cluster.
 *  - In any non-production environment (dev, test) the helper falls
 *    back to localhost so unit tests and `next dev` keep working
 *    without env-var ceremony.
 *
 * Both URLs are intentionally separate even though they currently
 * resolve to the same origin in production. The split lets us point
 * the marketing host at a static CDN later without touching every
 * call site.
 */

export interface SiteConfig {
  /** Origin of the office app (login, /office, /demo). */
  appUrl: string;
  /** Origin of the marketing/landing site (Footer brand link, etc.). */
  marketingUrl: string;
}

const LOCAL_FALLBACK = 'http://localhost:4301';

export function getSiteConfig(): SiteConfig {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL;
  const marketingUrl = process.env.NEXT_PUBLIC_MARKETING_URL;

  if (process.env.NODE_ENV === 'production' && (!appUrl || !marketingUrl)) {
    throw new Error(
      'NEXT_PUBLIC_APP_URL and NEXT_PUBLIC_MARKETING_URL must be set in production builds. ' +
        'Set them in your deployment environment to avoid leaking stale URLs.',
    );
  }

  return {
    appUrl: appUrl ?? LOCAL_FALLBACK,
    marketingUrl: marketingUrl ?? LOCAL_FALLBACK,
  };
}
