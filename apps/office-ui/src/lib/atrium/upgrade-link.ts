/**
 * Build a Dhanam pricing/upgrade URL for a not-entitled platform.
 *
 * The Atrium uses this to render the "Upgrade to access" CTA when the
 * operator's plan does not grant a given product. Lives in its own
 * module so the catalog stays focused on URL+verification metadata
 * and the launchpad stays focused on layout.
 *
 * Phase 1: link to the Dhanam pricing page with a `product=` query
 * parameter that Dhanam can use to highlight the relevant plan. Per
 * the ADR § Phase 2 we'll evolve this to a deep-link into the in-app
 * Dhanam upgrade flow once the pricing page supports it.
 */

const DHANAM_PRICING_BASE = 'https://dhan.am/pricing';

export function buildUpgradeUrl(slug: string): string {
  // Lowercase, URL-encoded slug — passed through as-is. Dhanam treats
  // unrecognized slugs as a no-op (just renders the generic page) so
  // forwards-compatibility is automatic for new platforms.
  const params = new URLSearchParams({
    product: slug,
    source: 'atrium',
  });
  return `${DHANAM_PRICING_BASE}?${params.toString()}`;
}
