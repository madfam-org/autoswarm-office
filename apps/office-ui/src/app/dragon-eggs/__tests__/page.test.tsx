/**
 * Page-level test for the admin gate.
 *
 * Mocks ``@/lib/api`` so we can flip ``getSessionUser`` + ``isAdmin``
 * between admin and non-admin states without touching real cookies.
 * Mocks the dragon-eggs api module so the page's effect doesn't hit
 * the network.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@/lib/api', () => ({
  getSessionUser: vi.fn(),
  isAdmin: vi.fn(),
  getSessionToken: () => null,
  apiFetch: vi.fn(),
  isGuest: () => false,
  isDemo: () => false,
}));

vi.mock('@/components/dragon-eggs/api', () => ({
  listEggs: vi.fn().mockResolvedValue([]),
  getEgg: vi.fn(),
  layEgg: vi.fn(),
  transitionEgg: vi.fn(),
  executeAction: vi.fn(),
  skipAction: vi.fn(),
  releaseEgg: vi.fn(),
}));

import * as api from '@/lib/api';
import DragonEggsPage from '../page';

describe('DragonEggsPage admin gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders 403 panel for non-admin tactician', async () => {
    vi.mocked(api.getSessionUser).mockReturnValue({
      sub: 'tact-1',
      email: 'tactician@example.com',
      roles: ['tactician'],
    });
    vi.mocked(api.isAdmin).mockReturnValue(false);

    render(<DragonEggsPage />);
    await waitFor(() => {
      expect(screen.getByText(/not authorized/i)).toBeInTheDocument();
    });
  });

  it('renders the page surface for admin@madfam.io', async () => {
    vi.mocked(api.getSessionUser).mockReturnValue({
      sub: 'founder',
      email: 'admin@madfam.io',
      roles: ['tactician'],
    });
    vi.mocked(api.isAdmin).mockReturnValue(false);

    render(<DragonEggsPage />);
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /dragon eggs/i })).toBeInTheDocument();
    });
  });

  it('renders the page for any user with the admin role', async () => {
    vi.mocked(api.getSessionUser).mockReturnValue({
      sub: 'ops-1',
      email: 'ops@selva.internal',
      roles: ['admin'],
    });
    vi.mocked(api.isAdmin).mockReturnValue(true);

    render(<DragonEggsPage />);
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /dragon eggs/i })).toBeInTheDocument();
    });
  });
});
