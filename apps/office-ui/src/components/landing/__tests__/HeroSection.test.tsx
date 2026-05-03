import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HeroSection } from '../HeroSection';

const TEST_APP_URL = 'https://app.selva.town';
const ORIGINAL_APP_URL = process.env.NEXT_PUBLIC_APP_URL;

describe('HeroSection', () => {
  // Pin NEXT_PUBLIC_APP_URL so the tests assert against a known origin
  // rather than the localhost dev fallback. Restore on teardown so other
  // suites that read this var aren't affected.
  beforeAll(() => {
    process.env.NEXT_PUBLIC_APP_URL = TEST_APP_URL;
  });
  afterAll(() => {
    if (ORIGINAL_APP_URL === undefined) {
      delete process.env.NEXT_PUBLIC_APP_URL;
    } else {
      process.env.NEXT_PUBLIC_APP_URL = ORIGINAL_APP_URL;
    }
  });

  it('renders the Selva brand title', () => {
    render(<HeroSection />);
    expect(screen.getByText('Selva')).toBeTruthy();
  });

  it('renders the tagline', () => {
    render(<HeroSection />);
    expect(screen.getByText(/Your AI workforce/)).toBeTruthy();
  });

  it('renders metrics', () => {
    render(<HeroSection />);
    expect(screen.getByText('Named Agents')).toBeTruthy();
    expect(screen.getByText('Built-in Tools')).toBeTruthy();
    expect(screen.getByText('Human-in-the-Loop')).toBeTruthy();
  });

  it('renders primary CTA linking to the demo', () => {
    render(<HeroSection />);
    const ctaLink = screen.getByText(/Try the Live Demo/);
    expect(ctaLink).toBeTruthy();
    expect(ctaLink.closest('a')?.getAttribute('href')).toBe(
      `${TEST_APP_URL}/demo`,
    );
  });

  it('renders Sign In CTA linking to the office app', () => {
    render(<HeroSection />);
    const signInLink = screen.getByText('Sign In');
    expect(signInLink).toBeTruthy();
    expect(signInLink.closest('a')?.getAttribute('href')).toBe(TEST_APP_URL);
  });
});
