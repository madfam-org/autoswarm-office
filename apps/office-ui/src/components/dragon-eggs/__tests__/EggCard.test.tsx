import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EggCard } from '../EggCard';
import type { Egg } from '../types';

const fakeEgg: Egg = {
  id: 'egg-1',
  persona_id: 'mx_compliance_voice',
  platform: 'mastodon',
  display_name: 'MX Compliance Voice',
  handle: '@mx_compliance@fosstodon.org',
  instance_url: 'https://fosstodon.org',
  status: 'incubating',
  progress: 0.4,
  laid_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
  hatched_at: null,
  matured_at: null,
  owner_org_id: 'madfam',
  created_by: 'admin@madfam.io',
  metadata: {},
};

describe('EggCard', () => {
  it('renders display name + handle + status + platform', () => {
    render(<EggCard egg={fakeEgg} onSelect={vi.fn()} />);
    expect(screen.getByText('MX Compliance Voice')).toBeInTheDocument();
    expect(screen.getByText('@mx_compliance@fosstodon.org')).toBeInTheDocument();
    expect(screen.getByText('Mastodon')).toBeInTheDocument();
    expect(screen.getByText('Incubating')).toBeInTheDocument();
  });

  it('renders the progress bar with correct ARIA value', () => {
    render(<EggCard egg={fakeEgg} onSelect={vi.fn()} />);
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('40');
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<EggCard egg={fakeEgg} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId(`egg-card-${fakeEgg.id}`));
    expect(onSelect).toHaveBeenCalledWith(fakeEgg);
  });

  it('reads as keyboard-focusable', () => {
    render(<EggCard egg={fakeEgg} onSelect={vi.fn()} />);
    const card = screen.getByTestId(`egg-card-${fakeEgg.id}`);
    // It's a <button>, so it's tab-focusable by default.
    expect(card.tagName.toLowerCase()).toBe('button');
  });

  it('shows "Autonomous tier" copy when matured', () => {
    render(
      <EggCard
        egg={{ ...fakeEgg, status: 'matured', progress: 1 }}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/autonomous tier/i)).toBeInTheDocument();
  });
});
