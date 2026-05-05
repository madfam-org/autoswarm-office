import { describe, it, expect, beforeEach } from 'vitest';
import {
  useAtriumStore,
  selectWindowsZOrdered,
  selectWindowsTaskbarOrdered,
} from '../atrium-windows';

beforeEach(() => {
  useAtriumStore.getState()._reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('useAtriumStore.open', () => {
  it('adds a new window with default windowed state', () => {
    useAtriumStore.getState().open({
      slug: 'karafiel',
      url: 'https://app.karafiel.mx',
      title: 'Karafiel',
    });
    const state = useAtriumStore.getState();
    expect(state.windows.karafiel).toBeDefined();
    expect(state.windows.karafiel.state).toBe('windowed');
    expect(state.focusedSlug).toBe('karafiel');
  });

  it('idempotently focuses an already-open window without remounting', () => {
    useAtriumStore.getState().open({
      slug: 'k',
      url: 'https://app.karafiel.mx',
      title: 'K',
    });
    const firstOpenedAt = useAtriumStore.getState().windows.k.openedAt;
    // re-open same slug
    useAtriumStore.getState().open({
      slug: 'k',
      url: 'https://app.karafiel.mx',
      title: 'K',
    });
    const after = useAtriumStore.getState();
    // openedAt unchanged → iframe identity preserved.
    expect(after.windows.k.openedAt).toBe(firstOpenedAt);
    expect(after.focusedSlug).toBe('k');
  });

  it('un-minimizes when opening a minimized slug', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'k', url: 'u', title: 'K' });
    s.minimize('k');
    expect(useAtriumStore.getState().windows.k.state).toBe('minimized');
    s.open({ slug: 'k', url: 'u', title: 'K' });
    expect(useAtriumStore.getState().windows.k.state).toBe('windowed');
  });

  it('persists geometry under atrium:layout:<slug>', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'k', url: 'u', title: 'K' });
    s.setGeometry('k', { x: 100, y: 200, width: 800, height: 600 });
    const raw = localStorage.getItem('atrium:layout:k');
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed).toMatchObject({ x: 100, y: 200, width: 800, height: 600 });
  });
});

describe('useAtriumStore.close', () => {
  it('removes the window and recomputes focus to highest remaining z', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.open({ slug: 'b', url: 'u', title: 'B' });
    s.open({ slug: 'c', url: 'u', title: 'C' });
    // c is currently focused (last opened)
    expect(useAtriumStore.getState().focusedSlug).toBe('c');
    s.close('c');
    // b had next-highest z
    expect(useAtriumStore.getState().focusedSlug).toBe('b');
    expect(useAtriumStore.getState().windows.c).toBeUndefined();
  });

  it('sets focus to null when last window closes', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'only', url: 'u', title: 'O' });
    s.close('only');
    expect(useAtriumStore.getState().focusedSlug).toBeNull();
  });
});

describe('useAtriumStore.focus', () => {
  it('promotes target z above all others', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.open({ slug: 'b', url: 'u', title: 'B' });
    s.focus('a');
    const after = useAtriumStore.getState();
    expect(after.focusedSlug).toBe('a');
    expect(after.windows.a.zIndex).toBeGreaterThan(after.windows.b.zIndex);
  });

  it('focusing a minimized window restores it to windowed', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.minimize('a');
    s.focus('a');
    expect(useAtriumStore.getState().windows.a.state).toBe('windowed');
  });
});

describe('useAtriumStore.maximize', () => {
  it('toggles to maximized and stores prevGeometry', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    const before = useAtriumStore.getState().windows.a.geometry;
    s.maximize('a');
    const after = useAtriumStore.getState().windows.a;
    expect(after.state).toBe('maximized');
    expect(after.prevGeometry).toEqual(before);
  });

  it('toggles back to windowed and restores prev geometry', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    const before = useAtriumStore.getState().windows.a.geometry;
    s.maximize('a');
    s.maximize('a');
    const after = useAtriumStore.getState().windows.a;
    expect(after.state).toBe('windowed');
    expect(after.geometry).toEqual(before);
  });
});

describe('atrium store selectors', () => {
  it('z-ordered selector sorts ascending by zIndex', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.open({ slug: 'b', url: 'u', title: 'B' });
    s.focus('a');
    const ordered = selectWindowsZOrdered({
      windows: useAtriumStore.getState().windows,
    });
    // a is now top (focused last)
    expect(ordered[ordered.length - 1].slug).toBe('a');
  });

  it('taskbar-ordered selector sorts by openedAt (stable)', async () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    // Tiny tick so openedAt differs even on fast machines.
    await new Promise((r) => setTimeout(r, 2));
    s.open({ slug: 'b', url: 'u', title: 'B' });
    // Focus a — should NOT change taskbar order.
    s.focus('a');
    const ordered = selectWindowsTaskbarOrdered({
      windows: useAtriumStore.getState().windows,
    });
    expect(ordered.map((w) => w.slug)).toEqual(['a', 'b']);
  });
});
