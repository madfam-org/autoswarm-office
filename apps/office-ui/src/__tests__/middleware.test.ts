import { describe, it, expect } from 'vitest';
import { NextRequest } from 'next/server';
import { middleware } from '../middleware';

function req(url: string, host: string): NextRequest {
  return new NextRequest(new URL(url), { headers: { host } });
}

describe('middleware host canonicalization', () => {
  it('301-redirects www.selva.town to the apex, preserving path + query', () => {
    const res = middleware(req('https://www.selva.town/demo?ref=x', 'www.selva.town'));
    expect(res.status).toBe(301);
    const loc = res.headers.get('location')!;
    const u = new URL(loc);
    expect(u.host).toBe('selva.town');
    expect(u.pathname).toBe('/demo');
    expect(u.searchParams.get('ref')).toBe('x');
  });

  it('leaves the apex host untouched (no redirect loop)', () => {
    const res = middleware(req('https://selva.town/', 'selva.town'));
    // Public path on the apex → pass through (not a 3xx to another host).
    expect(res.headers.get('location')).toBeNull();
  });

  it('still redirects app.selva.town root to /office', () => {
    const res = middleware(req('https://app.selva.town/', 'app.selva.town'));
    expect(res.status).toBe(307);
    expect(new URL(res.headers.get('location')!).pathname).toBe('/office');
  });
});
