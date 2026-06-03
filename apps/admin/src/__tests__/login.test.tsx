import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LoginPage from '../app/login/page';

const mockPush = vi.fn();

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Override the global mock for this test file
    vi.mocked(vi.fn()).mockClear?.();

    // Reset the router mock with a trackable push
    vi.doMock('next/navigation', () => ({
      useRouter: () => ({
        push: mockPush,
        replace: vi.fn(),
        back: vi.fn(),
        prefetch: vi.fn(),
      }),
      useSearchParams: () => new URLSearchParams(),
      usePathname: () => '/login',
    }));

    // Clear any cookies set by previous tests
    document.cookie =
      'janua-session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });

  it('renders the login page heading', () => {
    render(<LoginPage />);
    expect(screen.getByText('Selva Admin')).toBeInTheDocument();
  });

  it('shows the sign in description', () => {
    render(<LoginPage />);
    expect(screen.getByText('Sign in to access the admin console')).toBeInTheDocument();
  });

  it('renders the login button', () => {
    render(<LoginPage />);
    const loginBtn = screen.getByRole('button', {
      name: 'Login as Dev User',
    });
    expect(loginBtn).toBeInTheDocument();
  });

  it('shows the powered by Janua disclaimer', () => {
    render(<LoginPage />);
    expect(
      screen.getByText(
        'Powered by Janua',
      ),
    ).toBeInTheDocument();
  });

  it('sets a session cookie when the login button is clicked', () => {
    render(<LoginPage />);

    const loginBtn = screen.getByRole('button', {
      name: 'Login as Dev User',
    });
    fireEvent.click(loginBtn);

    // Verify that a janua-session cookie was set
    expect(document.cookie).toContain('janua-session=');
  });
});
