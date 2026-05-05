import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AtriumTaskbar } from '../AtriumTaskbar';
import { useAtriumStore } from '@/stores/atrium-windows';

beforeEach(() => {
  useAtriumStore.getState()._reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('AtriumTaskbar', () => {
  it('renders nothing when no windows are open', () => {
    const { container } = render(<AtriumTaskbar />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a chip per open window in open order', async () => {
    const open = useAtriumStore.getState().open;
    open({ slug: 'a', url: 'u', title: 'A' });
    await new Promise((r) => setTimeout(r, 2));
    open({ slug: 'b', url: 'u', title: 'B' });
    render(<AtriumTaskbar />);
    expect(screen.getByTestId('atrium-taskbar')).toBeInTheDocument();
    expect(screen.getByTestId('atrium-taskbar-chip-a')).toBeInTheDocument();
    expect(screen.getByTestId('atrium-taskbar-chip-b')).toBeInTheDocument();
  });

  it('chip carries data-state attribute reflecting window state', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.minimize('a');
    render(<AtriumTaskbar />);
    expect(screen.getByTestId('atrium-taskbar-chip-a')).toHaveAttribute(
      'data-state',
      'minimized',
    );
  });

  it('right-click on chip closes the window', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    render(<AtriumTaskbar />);
    fireEvent.contextMenu(screen.getByTestId('atrium-taskbar-chip-a'));
    expect(useAtriumStore.getState().windows.a).toBeUndefined();
  });

  it('clicking chip focuses the window', () => {
    const s = useAtriumStore.getState();
    s.open({ slug: 'a', url: 'u', title: 'A' });
    s.open({ slug: 'b', url: 'u', title: 'B' });
    // currently focused: b
    render(<AtriumTaskbar />);
    fireEvent.click(screen.getByTestId('atrium-taskbar-chip-a'));
    expect(useAtriumStore.getState().focusedSlug).toBe('a');
  });
});
