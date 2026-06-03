import '@testing-library/jest-dom/vitest';

// Mock next/navigation globally since all admin pages use 'use client' with hooks
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}));

// Mock next/link to render a plain anchor
vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// Mock next/font/google
vi.mock('next/font/google', () => ({
  Inter: () => ({ variable: '--font-inter' }),
}));

// Mock PostHog analytics
vi.mock('@/lib/analytics/posthog', () => ({
  initPostHog: vi.fn(),
}));

// Mock @janua/nextjs-sdk
vi.mock('@janua/nextjs-sdk', () => ({
  JanuaProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// Mock @selva/ui Button component
vi.mock('@selva/ui', () => ({
  Button: ({
    children,
    onClick,
    disabled,
    type,
    ...props
  }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    type?: string;
    [key: string]: unknown;
  }) => (
    <button
      type={type === 'submit' ? 'submit' : 'button'}
      onClick={onClick}
      disabled={disabled}
      data-variant={props.variant}
      data-size={props.size}
    >
      {children}
    </button>
  ),
}));

// Reset fetch mock before each test
beforeEach(() => {
  vi.restoreAllMocks();
});
