import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AtriumLaunchpad } from '../AtriumLaunchpad';
import { useEntitlementsStore } from '@/stores/entitlements';
import { useAtriumStore } from '@/stores/atrium-windows';

// next/navigation is not available in jsdom — stub the router push.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// useIsMadfamAdmin reads getSessionUser, which calls document.cookie.
// Default to non-admin in these tests; one test overrides via the hook mock.
vi.mock('@/hooks/useIsMadfamAdmin', () => ({
  useIsMadfamAdmin: vi.fn(() => false),
}));

// useEntitlements triggers a fetch on mount; we set the store directly per
// test, so make the hook a no-op to avoid racing the configured state.
vi.mock('@/hooks/useEntitlements', () => ({
  useEntitlements: vi.fn(() => undefined),
}));

beforeEach(() => {
  useEntitlementsStore.getState()._reset();
  useAtriumStore.getState()._reset();
  // Stub fetch so the on-mount useEntitlements doesn't actually hit the network.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ products: [], claim_string_form: [] }),
    } as unknown as Response),
  );
});

describe('AtriumLaunchpad entitlement gating', () => {
  it('renders skeleton state while entitlements are loading', () => {
    // Force loading state — _hydrate sets ready, so we set manually.
    useEntitlementsStore.setState({ status: 'loading' });

    render(<AtriumLaunchpad />);

    // At least one of the catalog tiles should be in loading state with a skeleton.
    const tile = screen.getByTestId('atrium-launchpad-tile-karafiel');
    expect(tile.getAttribute('data-state')).toBe('loading');
    expect(
      screen.getByTestId('atrium-launchpad-tile-karafiel-skeleton'),
    ).toBeInTheDocument();
    // Open button must NOT be present while loading.
    expect(
      screen.queryByTestId('atrium-launchpad-tile-karafiel-open'),
    ).not.toBeInTheDocument();
  });

  it('renders entitled tile (Open in Atrium button) for granted slugs', () => {
    useEntitlementsStore.getState()._hydrate({
      products: [
        {
          slug: 'karafiel',
          tier: 'contador',
          expires_at: null,
          source: 'dhanam_subscription',
        },
      ],
      claim_string_form: ['karafiel:contador'],
    });

    render(<AtriumLaunchpad />);

    const tile = screen.getByTestId('atrium-launchpad-tile-karafiel');
    expect(tile.getAttribute('data-state')).toBe('entitled');
    expect(
      screen.getByTestId('atrium-launchpad-tile-karafiel-open'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('atrium-launchpad-tile-karafiel-upgrade'),
    ).not.toBeInTheDocument();
    // Tier surfaces in the UI so the operator knows what they're on.
    expect(
      screen.getByTestId('atrium-launchpad-tile-karafiel-tier').textContent,
    ).toContain('contador');
  });

  it('renders upgrade tile for ungranted slugs once entitlements are ready', () => {
    // Ready, but karafiel is not in the entitled set.
    useEntitlementsStore.getState()._hydrate({
      products: [
        { slug: 'dhanam', tier: 'pro', expires_at: null, source: 'dhanam_subscription' },
      ],
      claim_string_form: ['dhanam:pro'],
    });

    render(<AtriumLaunchpad />);

    const tile = screen.getByTestId('atrium-launchpad-tile-karafiel');
    expect(tile.getAttribute('data-state')).toBe('not-entitled');
    const upgradeLink = screen.getByTestId(
      'atrium-launchpad-tile-karafiel-upgrade',
    ) as HTMLAnchorElement;
    expect(upgradeLink).toBeInTheDocument();
    expect(upgradeLink.href).toContain('dhan.am/pricing');
    expect(upgradeLink.href).toContain('product=karafiel');
    // Open button is absent for not-entitled tiles.
    expect(
      screen.queryByTestId('atrium-launchpad-tile-karafiel-open'),
    ).not.toBeInTheDocument();
  });

  it('fail-open: error state renders the entitled tile (no upgrade gate)', () => {
    useEntitlementsStore.setState({
      status: 'error',
      errorMessage: 'unauthenticated',
      entitledSlugs: new Set(),
      tierBySlug: {},
    });

    render(<AtriumLaunchpad />);

    const tile = screen.getByTestId('atrium-launchpad-tile-karafiel');
    // data-state derives from `gated`; in error state shouldGateSlug returns false.
    expect(tile.getAttribute('data-state')).toBe('entitled');
    expect(
      screen.getByTestId('atrium-launchpad-tile-karafiel-open'),
    ).toBeInTheDocument();
  });
});
