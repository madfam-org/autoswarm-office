import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

import {
  useJumanjiState,
  JUMANJI_TEST_HOOKS,
} from '../easter-eggs/useJumanjiState';
import { buildPortalUrl, JUMANJI_EVENTS } from '../easter-eggs/jumanjiAnalytics';
import { JumanjiDeviceImpl } from '../easter-eggs/JumanjiDeviceImpl';

// Mock the analytics module so we can spy on emissions.
const mockTrack = vi.fn();
vi.mock('@/lib/analytics/posthog', () => ({
  trackEvent: (...args: unknown[]) => mockTrack(...args),
  initPostHog: () => {},
  identifyUser: () => {},
  resetUser: () => {},
}));

// Mock useFocusTrap (uses DOM APIs we don't need to exercise here).
vi.mock('@/hooks/useFocusTrap', () => ({
  useFocusTrap: () => ({ current: null }),
}));

beforeEach(() => {
  mockTrack.mockClear();
  window.localStorage.clear();
  // Reset URL to avoid the reset_jumanji query param leaking between tests.
  window.history.replaceState({}, '', '/');
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('useJumanjiState — state machine', () => {
  it('starts in resting when no localStorage flag', () => {
    const { result } = renderHook(() => useJumanjiState());
    expect(result.current.state).toBe('resting');
    expect(result.current.discovered).toBe(false);
    expect(result.current.progress).toBe(0);
  });

  it('starts in curious when previously discovered', () => {
    window.localStorage.setItem(JUMANJI_TEST_HOOKS.STORAGE_KEY, 'true');
    const { result } = renderHook(() => useJumanjiState());
    expect(result.current.state).toBe('curious');
    expect(result.current.discovered).toBe(true);
  });

  it('?reset_jumanji=1 wipes the discovery flag', () => {
    window.localStorage.setItem(JUMANJI_TEST_HOOKS.STORAGE_KEY, 'true');
    window.history.replaceState({}, '', '/?reset_jumanji=1');
    const { result } = renderHook(() => useJumanjiState());
    expect(result.current.state).toBe('resting');
    expect(window.localStorage.getItem(JUMANJI_TEST_HOOKS.STORAGE_KEY)).toBeNull();
  });

  it('typing JUMANJI advances to portal and persists discovery', () => {
    const { result } = renderHook(() => useJumanjiState());
    // Bring it into curious via focus first.
    act(() => result.current.onFocus());
    expect(result.current.state).toBe('curious');

    const sequence = JUMANJI_TEST_HOOKS.SEQUENCE.split('');
    for (const letter of sequence) {
      act(() => {
        result.current.onKeyDown({
          key: letter,
          preventDefault: () => {},
        } as unknown as React.KeyboardEvent);
      });
    }
    expect(result.current.state).toBe('portal');
    expect(window.localStorage.getItem(JUMANJI_TEST_HOOKS.STORAGE_KEY)).toBe('true');
  });

  it('wrong letter resets sequence (unless it is "J")', () => {
    const { result } = renderHook(() => useJumanjiState());
    act(() => result.current.onFocus());

    act(() => {
      result.current.onKeyDown({ key: 'J', preventDefault: () => {} } as unknown as React.KeyboardEvent);
    });
    expect(result.current.progress).toBe(1);

    act(() => {
      result.current.onKeyDown({ key: 'X', preventDefault: () => {} } as unknown as React.KeyboardEvent);
    });
    expect(result.current.progress).toBe(0);
  });

  it('three taps within window advance to portal (touch fallback)', () => {
    const { result } = renderHook(() => useJumanjiState());
    act(() => result.current.onActivate()); // resting -> curious
    act(() => result.current.onActivate()); // tap 1 (counts; curious -> awakened)
    act(() => result.current.onActivate()); // tap 2
    act(() => result.current.onActivate()); // tap 3 -> portal (3 taps within window)
    expect(result.current.state).toBe('portal');
  });

  it('reset() returns to curious when previously discovered', () => {
    window.localStorage.setItem(JUMANJI_TEST_HOOKS.STORAGE_KEY, 'true');
    const { result } = renderHook(() => useJumanjiState());
    act(() => result.current.onFocus());
    act(() => {
      for (const k of JUMANJI_TEST_HOOKS.SEQUENCE) {
        result.current.onKeyDown({
          key: k,
          preventDefault: () => {},
        } as unknown as React.KeyboardEvent);
      }
    });
    expect(result.current.state).toBe('portal');
    act(() => result.current.reset());
    expect(result.current.state).toBe('curious');
  });
});

describe('useJumanjiState — reduced motion', () => {
  it('reflects prefers-reduced-motion: reduce', () => {
    const matchMediaSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: query.includes('reduce'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));
    const { result } = renderHook(() => useJumanjiState());
    expect(result.current.reducedMotion).toBe(true);
    matchMediaSpy.mockRestore();
  });
});

describe('buildPortalUrl', () => {
  it('appends UTM params and base URL', () => {
    const url = buildPortalUrl();
    expect(url).toContain('https://play.rondel.io/');
    expect(url).toContain('utm_source=selva');
    expect(url).toContain('utm_medium=easter_egg');
    expect(url).toContain('utm_campaign=jumanji_device');
    expect(url).toContain('utm_content=device_v1');
  });

  it('includes user_id and org_id when provided', () => {
    const url = buildPortalUrl({ userId: 'u-1', orgId: 'o-2' });
    expect(url).toContain('selva_uid=u-1');
    expect(url).toContain('selva_org=o-2');
  });

  it('omits selva_uid when no userId', () => {
    const url = buildPortalUrl({ orgId: 'o-2' });
    expect(url).not.toContain('selva_uid');
    expect(url).toContain('selva_org=o-2');
  });
});

describe('JumanjiDeviceImpl — analytics + a11y', () => {
  it('emits seen event on mount', () => {
    render(<JumanjiDeviceImpl currentPage="/status" userId="u-1" orgId="o-1" />);
    const seenCalls = mockTrack.mock.calls.filter((c) => c[0] === JUMANJI_EVENTS.SEEN);
    expect(seenCalls.length).toBeGreaterThanOrEqual(1);
    expect(seenCalls[0]?.[1]).toMatchObject({
      user_id: 'u-1',
      org_id: 'o-1',
      current_page: '/status',
      variant: 'device_v1',
    });
  });

  it('exposes aria-label and is keyboard reachable', () => {
    render(<JumanjiDeviceImpl currentPage="/status" />);
    const btn = screen.getByRole('button', { name: /mysterious device/i });
    expect(btn).toHaveAttribute('tabIndex', '0');
    expect(btn).toHaveAttribute('aria-label');
  });

  it('typing JUMANJI emits activated event', () => {
    render(<JumanjiDeviceImpl currentPage="/status" />);
    const btn = screen.getByRole('button', { name: /mysterious device/i });
    btn.focus();
    for (const k of JUMANJI_TEST_HOOKS.SEQUENCE) {
      fireEvent.keyDown(btn, { key: k });
    }
    const activated = mockTrack.mock.calls.filter((c) => c[0] === JUMANJI_EVENTS.ACTIVATED);
    expect(activated.length).toBe(1);
    expect(activated[0]?.[1]).toMatchObject({ current_page: '/status', variant: 'device_v1' });
  });

  it('reaches portal state and shows Step in CTA', () => {
    render(<JumanjiDeviceImpl currentPage="/status" />);
    const btn = screen.getByRole('button', { name: /mysterious device/i });
    btn.focus();
    for (const k of JUMANJI_TEST_HOOKS.SEQUENCE) {
      fireEvent.keyDown(btn, { key: k });
    }
    expect(screen.getByRole('status')).toHaveTextContent(/step in/i);
    expect(btn.getAttribute('data-jumanji-state')).toBe('portal');
  });
});
