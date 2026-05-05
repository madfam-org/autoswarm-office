import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EggArt } from '../EggArt';
import { EGG_STATUS_ORDER } from '../types';

describe('EggArt', () => {
  it.each(EGG_STATUS_ORDER)('renders the %s stage', (status) => {
    render(<EggArt status={status} platform="bluesky" />);
    const svg = screen.getByTestId(`egg-art-${status}`);
    expect(svg).toBeInTheDocument();
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(svg.getAttribute('aria-label')).toContain(status);
  });

  it('shows cracks at hatching/hatched/matured but not laid/incubating', () => {
    const { container, rerender } = render(<EggArt status="laid" platform="reddit" />);
    expect(container.querySelector('.egg-art-cracks')).toBeNull();

    rerender(<EggArt status="incubating" platform="reddit" />);
    expect(container.querySelector('.egg-art-cracks')).toBeNull();

    rerender(<EggArt status="hatching" platform="reddit" />);
    expect(container.querySelector('.egg-art-cracks')).not.toBeNull();

    rerender(<EggArt status="hatched" platform="reddit" />);
    expect(container.querySelector('.egg-art-cracks')).not.toBeNull();

    rerender(<EggArt status="matured" platform="reddit" />);
    expect(container.querySelector('.egg-art-cracks')).not.toBeNull();
  });

  it('renders the matured dragon body for matured stage', () => {
    const { container } = render(<EggArt status="matured" platform="bluesky" />);
    expect(container.querySelector('.egg-art-dragon')).not.toBeNull();
  });

  it('renders the hatchling for hatched stage (not the full dragon)', () => {
    const { container } = render(<EggArt status="hatched" platform="reddit" />);
    expect(container.querySelector('.egg-art-hatchling')).not.toBeNull();
    expect(container.querySelector('.egg-art-dragon')).toBeNull();
  });

  it('does not render glow halo at laid stage', () => {
    const { container } = render(<EggArt status="laid" platform="bluesky" />);
    expect(container.querySelector('.egg-art-glow')).toBeNull();
  });

  it('renders glow halo at incubating onward', () => {
    const { container, rerender } = render(<EggArt status="incubating" platform="bluesky" />);
    expect(container.querySelector('.egg-art-glow')).not.toBeNull();
    rerender(<EggArt status="hatched" platform="bluesky" />);
    expect(container.querySelector('.egg-art-glow')).not.toBeNull();
  });

  it('respects the size prop', () => {
    render(<EggArt status="laid" platform="bluesky" size={48} />);
    const svg = screen.getByTestId('egg-art-laid');
    expect(svg.getAttribute('width')).toBe('48');
    expect(svg.getAttribute('height')).toBe('48');
  });

  it('embeds an animation gate behind prefers-reduced-motion: no-preference', () => {
    const { container } = render(<EggArt status="incubating" platform="reddit" />);
    const style = container.querySelector('style');
    // The inline <style> only enables animation when the user has not
    // requested reduced motion.
    expect(style?.textContent).toContain('prefers-reduced-motion: no-preference');
    expect(style?.textContent).toContain('@keyframes egg-glow-pulse');
  });
});
