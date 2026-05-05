import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  useEntitlementsStore,
  shouldGateSlug,
  type EntitlementsApiResponse,
} from '../entitlements';

beforeEach(() => {
  useEntitlementsStore.getState()._reset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useEntitlementsStore selectors', () => {
  it('starts in idle with no entitled slugs', () => {
    const s = useEntitlementsStore.getState();
    expect(s.status).toBe('idle');
    expect(s.entitledSlugs.size).toBe(0);
    expect(s.isEntitled('karafiel')).toBe(false);
    expect(s.tierFor('karafiel')).toBeUndefined();
  });

  it('_hydrate populates entitledSlugs and tierBySlug', () => {
    const fixture: EntitlementsApiResponse = {
      products: [
        { slug: 'karafiel', tier: 'contador', expires_at: null, source: 'dhanam_subscription' },
        { slug: 'dhanam', tier: 'pro', expires_at: null, source: 'dhanam_subscription' },
      ],
      claim_string_form: ['dhanam:pro', 'karafiel:contador'],
    };
    useEntitlementsStore.getState()._hydrate(fixture);
    const s = useEntitlementsStore.getState();
    expect(s.status).toBe('ready');
    expect(s.isEntitled('karafiel')).toBe(true);
    expect(s.isEntitled('dhanam')).toBe(true);
    expect(s.isEntitled('selva')).toBe(false);
    expect(s.tierFor('karafiel')).toBe('contador');
  });
});

describe('shouldGateSlug selector', () => {
  it('returns false while loading (renders skeleton, not upgrade)', () => {
    expect(
      shouldGateSlug('karafiel', { status: 'loading', entitledSlugs: new Set() }),
    ).toBe(false);
  });

  it('returns false on error (fail-open)', () => {
    expect(
      shouldGateSlug('karafiel', { status: 'error', entitledSlugs: new Set() }),
    ).toBe(false);
  });

  it('returns true when ready and slug missing', () => {
    expect(
      shouldGateSlug('karafiel', { status: 'ready', entitledSlugs: new Set() }),
    ).toBe(true);
  });

  it('returns false when ready and slug present', () => {
    expect(
      shouldGateSlug('karafiel', {
        status: 'ready',
        entitledSlugs: new Set(['karafiel']),
      }),
    ).toBe(false);
  });
});

describe('useEntitlementsStore.fetch', () => {
  it('hydrates store on a successful 200', async () => {
    const fixture: EntitlementsApiResponse = {
      products: [
        { slug: 'karafiel', tier: 'pro', expires_at: null, source: 'dhanam_subscription' },
      ],
      claim_string_form: ['karafiel:pro'],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => fixture,
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useEntitlementsStore.getState().fetch('https://auth.test');

    const s = useEntitlementsStore.getState();
    expect(s.status).toBe('ready');
    expect(s.isEntitled('karafiel')).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();
    const calledUrl = (fetchMock.mock.calls[0]![0] as string);
    expect(calledUrl).toBe('https://auth.test/api/v1/me/entitlements');
  });

  it('flips to error on 401 (fail-open: gating disabled)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useEntitlementsStore.getState().fetch('https://auth.test');

    const s = useEntitlementsStore.getState();
    expect(s.status).toBe('error');
    expect(s.errorMessage).toBe('unauthenticated');
    // Fail-open invariant: shouldGateSlug must be false in error state.
    expect(
      shouldGateSlug('karafiel', { status: s.status, entitledSlugs: s.entitledSlugs }),
    ).toBe(false);
  });

  it('flips to error on a 500 (fail-open)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useEntitlementsStore.getState().fetch('https://auth.test');

    const s = useEntitlementsStore.getState();
    expect(s.status).toBe('error');
    expect(
      shouldGateSlug('karafiel', { status: s.status, entitledSlugs: s.entitledSlugs }),
    ).toBe(false);
  });

  it('flips to error on a network reject', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    vi.stubGlobal('fetch', fetchMock);

    await useEntitlementsStore.getState().fetch('https://auth.test');

    expect(useEntitlementsStore.getState().status).toBe('error');
  });

  it('is idempotent — concurrent fetches do not double-call the network', async () => {
    let resolver: (value: Response) => void = () => {};
    const pending = new Promise<Response>((res) => {
      resolver = res;
    });
    const fetchMock = vi.fn().mockImplementation(() => pending);
    vi.stubGlobal('fetch', fetchMock);

    const promises = [
      useEntitlementsStore.getState().fetch('https://auth.test'),
      useEntitlementsStore.getState().fetch('https://auth.test'),
      useEntitlementsStore.getState().fetch('https://auth.test'),
    ];
    // Only one network call should have been issued.
    expect(fetchMock).toHaveBeenCalledOnce();

    resolver({
      ok: true,
      status: 200,
      json: async () => ({ products: [], claim_string_form: [] }),
    } as unknown as Response);
    await Promise.all(promises);
  });

  it('attaches Bearer token when janua-session cookie is present', async () => {
    Object.defineProperty(document, 'cookie', {
      value: 'janua-session=eyTOKEN.signed.payload',
      configurable: true,
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ products: [], claim_string_form: [] }),
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useEntitlementsStore.getState().fetch('https://auth.test');

    const callArgs = fetchMock.mock.calls[0];
    expect(callArgs).toBeDefined();
    const init = callArgs![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer eyTOKEN.signed.payload');
  });
});
