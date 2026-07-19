import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import PricingPage from '../page';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetchMock(...args) };
});

const addToastMock = vi.fn();
vi.mock('@/hooks/useToast', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useToast')>(
    '@/hooks/useToast',
  );
  return { ...actual, useToast: () => ({ toasts: [], addToast: addToastMock, removeToast: vi.fn() }) };
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const TIERS = {
  tiers: [
    { slug: 'starter', name: 'Starter', daily_token_limit: 1000 },
    { slug: 'professional', name: 'Professional', daily_token_limit: 5000 },
    { slug: 'enterprise', name: 'Enterprise', daily_token_limit: 25000 },
  ],
};

describe('PricingPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    addToastMock.mockReset();
  });

  it('renders a card per tier from the API', async () => {
    apiFetchMock.mockResolvedValueOnce(json(TIERS));
    render(<PricingPage />);

    expect(await screen.findByText('Starter')).toBeInTheDocument();
    expect(screen.getByText('Professional')).toBeInTheDocument();
    expect(screen.getByText('Enterprise')).toBeInTheDocument();
    expect(screen.getByText('5,000')).toBeInTheDocument(); // pro daily limit
    expect(screen.getAllByRole('button', { name: /choose/i })).toHaveLength(3);
  });

  it('shows a truthful "coming soon" toast when checkout is not_configured (501)', async () => {
    apiFetchMock
      .mockResolvedValueOnce(json(TIERS)) // /billing/tiers
      .mockResolvedValueOnce(
        json({ detail: { status: 'not_configured' } }, 501), // /billing/checkout
      );
    render(<PricingPage />);

    const chooseButtons = await screen.findAllByRole('button', { name: /choose/i });
    fireEvent.click(chooseButtons[1]); // Professional

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/billing/checkout',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(addToastMock).toHaveBeenCalledWith(
        expect.stringMatching(/coming soon/i),
        'info',
      );
    });
  });

  it('renders a graceful error when tiers fail to load', async () => {
    apiFetchMock.mockResolvedValueOnce(json({}, 500));
    render(<PricingPage />);
    expect(await screen.findByText(/couldn.t load plans/i)).toBeInTheDocument();
  });
});
