import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EggGrid } from '../EggGrid';
import type { Egg } from '../types';

const sampleEgg: Egg = {
  id: 'egg-1',
  persona_id: 'p',
  platform: 'reddit',
  display_name: 'Reddit Voice',
  handle: 'u/x',
  instance_url: null,
  status: 'laid',
  progress: 0,
  laid_at: new Date().toISOString(),
  hatched_at: null,
  matured_at: null,
  owner_org_id: 'madfam',
  created_by: 'admin',
  metadata: {},
};

describe('EggGrid', () => {
  it('shows loading state', () => {
    render(<EggGrid eggs={[]} loading onSelect={vi.fn()} onLayFirst={vi.fn()} />);
    expect(screen.getByText(/loading eggs/i)).toBeInTheDocument();
  });

  it('shows error state', () => {
    render(
      <EggGrid eggs={[]} error="boom" onSelect={vi.fn()} onLayFirst={vi.fn()} />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
  });

  it('shows empty state with CTA', () => {
    const onLayFirst = vi.fn();
    render(
      <EggGrid eggs={[]} onSelect={vi.fn()} onLayFirst={onLayFirst} />,
    );
    expect(screen.getByText(/no dragons yet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /lay an egg/i }));
    expect(onLayFirst).toHaveBeenCalled();
  });

  it('renders cards for each egg', () => {
    render(<EggGrid eggs={[sampleEgg]} onSelect={vi.fn()} onLayFirst={vi.fn()} />);
    expect(screen.getByTestId(`egg-card-${sampleEgg.id}`)).toBeInTheDocument();
  });
});
