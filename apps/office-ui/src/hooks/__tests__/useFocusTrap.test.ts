import { renderHook } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useFocusTrap } from '../useFocusTrap';

describe('useFocusTrap', () => {
  it('returns a ref object', () => {
    const { result } = renderHook(() => useFocusTrap(false));
    expect(result.current).toHaveProperty('current');
    expect(result.current.current).toBeNull();
  });

  it('returns a stable ref across re-renders', () => {
    const { result, rerender } = renderHook(
      ({ active }) => useFocusTrap(active),
      { initialProps: { active: false } },
    );

    const firstRef = result.current;
    rerender({ active: false });
    expect(result.current).toBe(firstRef);
  });

  it('does not throw when active with no container', () => {
    // Active but ref not attached to DOM — should not throw
    expect(() => {
      renderHook(() => useFocusTrap(true));
    }).not.toThrow();
  });
});
