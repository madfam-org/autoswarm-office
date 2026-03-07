import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ErrorBoundary } from '../ErrorBoundary';

// Suppress React error boundary console.error noise
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test crash');
  }
  return <div>Child OK</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Child OK')).toBeInTheDocument();
  });

  it('renders fallback UI when a child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('SOMETHING WENT WRONG')).toBeInTheDocument();
    expect(screen.getByText('Test crash')).toBeInTheDocument();
  });

  it('renders a Try Again button in fallback', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Try Again')).toBeInTheDocument();
  });

  it('Try Again button is clickable without crashing', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('SOMETHING WENT WRONG')).toBeInTheDocument();

    // Clicking Try Again should not throw (it resets state internally)
    expect(() => {
      fireEvent.click(screen.getByText('Try Again'));
    }).not.toThrow();
  });
});
