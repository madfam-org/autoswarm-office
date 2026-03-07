import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ToastProvider } from '../Toast';
import { useToast } from '../../hooks/useToast';

// Helper component that exposes addToast
function ToastTrigger() {
  const { addToast } = useToast();
  return (
    <div>
      <button onClick={() => addToast('Success message', 'success')}>
        Add Success
      </button>
      <button onClick={() => addToast('Error message', 'error')}>
        Add Error
      </button>
      <button onClick={() => addToast('Info message')}>
        Add Info
      </button>
    </div>
  );
}

describe('Toast system', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders no toasts initially', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a toast when addToast is called', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Success'));
    expect(screen.getByText('Success message')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('applies correct severity styling', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Error'));
    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('border-red-500');
  });

  it('defaults to info severity', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Info'));
    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('border-indigo-500');
  });

  it('auto-dismisses after 5 seconds plus exit animation', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Success'));
    expect(screen.getByText('Success message')).toBeInTheDocument();

    // 5s auto-dismiss + 200ms exit animation delay
    act(() => {
      vi.advanceTimersByTime(5200);
    });

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
  });

  it('can be manually dismissed after exit animation', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Success'));
    expect(screen.getByText('Success message')).toBeInTheDocument();

    const dismissBtn = screen.getByLabelText('Dismiss');
    fireEvent.click(dismissBtn);

    // Still visible during exit animation
    expect(screen.getByText('Success message')).toBeInTheDocument();

    // Removed after 200ms exit animation
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
  });

  it('can show multiple toasts', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText('Add Success'));
    fireEvent.click(screen.getByText('Add Error'));

    expect(screen.getByText('Success message')).toBeInTheDocument();
    expect(screen.getByText('Error message')).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(2);
  });
});
