import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useToastState } from '../../hooks/useToast';

describe('useToastState', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts with empty toasts', () => {
    const { result } = renderHook(() => useToastState());
    expect(result.current.toasts).toEqual([]);
  });

  it('addToast adds a toast with generated id', () => {
    const { result } = renderHook(() => useToastState());

    act(() => {
      result.current.addToast('Hello', 'info');
    });

    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].message).toBe('Hello');
    expect(result.current.toasts[0].severity).toBe('info');
    expect(result.current.toasts[0].id).toBeTruthy();
  });

  it('defaults severity to info', () => {
    const { result } = renderHook(() => useToastState());

    act(() => {
      result.current.addToast('Default severity');
    });

    expect(result.current.toasts[0].severity).toBe('info');
  });

  it('removeToast removes by id', () => {
    const { result } = renderHook(() => useToastState());

    act(() => {
      result.current.addToast('First', 'success');
      result.current.addToast('Second', 'error');
    });

    expect(result.current.toasts).toHaveLength(2);

    const idToRemove = result.current.toasts[0].id;
    act(() => {
      result.current.removeToast(idToRemove);
    });

    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].message).toBe('Second');
  });

  it('auto-dismisses after 5 seconds', () => {
    const { result } = renderHook(() => useToastState());

    act(() => {
      result.current.addToast('Ephemeral', 'warning');
    });

    expect(result.current.toasts).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current.toasts).toHaveLength(0);
  });

  it('can add multiple toasts', () => {
    const { result } = renderHook(() => useToastState());

    act(() => {
      result.current.addToast('A', 'success');
      result.current.addToast('B', 'error');
      result.current.addToast('C', 'warning');
    });

    expect(result.current.toasts).toHaveLength(3);
  });
});
