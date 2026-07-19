import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { WelcomeTour, hasSeenWelcomeTour } from '../WelcomeTour';

describe('WelcomeTour', () => {
  beforeEach(() => {
    try {
      localStorage.clear();
    } catch {
      /* jsdom */
    }
  });

  it('renders nothing when closed', () => {
    const { container } = render(<WelcomeTour open={false} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it('walks through all steps and marks itself seen on finish', () => {
    const onClose = vi.fn();
    render(<WelcomeTour open onClose={onClose} />);

    // Step 1
    expect(screen.getByText(/Welcome to your Selva office/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 4/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /next/i })); // → 2
    expect(screen.getByText(/agents are teammates/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /next/i })); // → 3
    expect(screen.getByText(/Put an agent to work/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /next/i })); // → 4 (last)

    // Last step shows "Get started" and finishes.
    const finishBtn = screen.getByRole('button', { name: /get started/i });
    expect(hasSeenWelcomeTour()).toBe(false);
    fireEvent.click(finishBtn);
    expect(onClose).toHaveBeenCalled();
    expect(hasSeenWelcomeTour()).toBe(true);
  });

  it('Skip finishes immediately and persists the seen flag', () => {
    const onClose = vi.fn();
    render(<WelcomeTour open onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /skip/i }));
    expect(onClose).toHaveBeenCalled();
    expect(hasSeenWelcomeTour()).toBe(true);
  });

  it('hasSeenWelcomeTour reflects the persisted flag', () => {
    expect(hasSeenWelcomeTour()).toBe(false);
    localStorage.setItem('selva:welcome-tour-seen', '1');
    expect(hasSeenWelcomeTour()).toBe(true);
  });
});
