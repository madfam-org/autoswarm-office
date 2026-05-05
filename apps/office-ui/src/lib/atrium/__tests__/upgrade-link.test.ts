import { describe, it, expect } from 'vitest';
import { buildUpgradeUrl } from '../upgrade-link';

describe('buildUpgradeUrl', () => {
  it('targets the Dhanam pricing page', () => {
    const url = buildUpgradeUrl('karafiel');
    expect(url.startsWith('https://dhan.am/pricing?')).toBe(true);
  });

  it('includes the product slug as a query param', () => {
    const url = buildUpgradeUrl('karafiel');
    expect(url).toContain('product=karafiel');
  });

  it('tags the source so Dhanam knows the upgrade came from Atrium', () => {
    const url = buildUpgradeUrl('karafiel');
    expect(url).toContain('source=atrium');
  });

  it('URL-encodes hyphens-and-special-chars in slugs without altering semantics', () => {
    const url = buildUpgradeUrl('phyne-crm');
    // URLSearchParams keeps hyphens as-is (they don't need encoding).
    expect(url).toContain('product=phyne-crm');
  });
});
