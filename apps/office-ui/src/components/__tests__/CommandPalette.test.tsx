import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CommandPalette, type PaletteAction } from '../CommandPalette';
import type { Department, Player } from '@selva/shared-types';

function player(over: Partial<Player>): Player {
  return {
    sessionId: 's1',
    name: 'Alice',
    x: 0,
    y: 0,
    direction: 'down',
    playerStatus: 'online',
    ...over,
  } as Player;
}

function dept(agents: Array<Partial<{ id: string; name: string; role: string; status: string }>>): Department {
  return {
    id: 'd1',
    name: 'Eng',
    agents: agents.map((a, i) => ({
      id: a.id ?? `a${i}`,
      name: a.name ?? `Agent${i}`,
      role: a.role ?? 'coder',
      status: a.status ?? 'idle',
    })),
  } as unknown as Department;
}

const action = (over: Partial<PaletteAction> = {}): PaletteAction => ({
  id: 'dispatch',
  label: 'Dispatch a task',
  glyph: '⚡',
  run: vi.fn(),
  ...over,
});

describe('CommandPalette', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <CommandPalette open={false} onClose={() => {}} players={[]} departments={[]} actions={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('lists actions, people, and agents together', () => {
    render(
      <CommandPalette
        open
        onClose={() => {}}
        players={[player({ name: 'Aldo' })]}
        departments={[dept([{ name: 'Atlas', role: 'planner', status: 'working' }])]}
        actions={[action()]}
      />,
    );
    expect(screen.getByText('Dispatch a task')).toBeInTheDocument();
    expect(screen.getByText('Aldo')).toBeInTheDocument();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText(/planner · Working/)).toBeInTheDocument();
  });

  it('filters by query across name and sub-text', () => {
    render(
      <CommandPalette
        open
        onClose={() => {}}
        players={[player({ name: 'Aldo' }), player({ sessionId: 's2', name: 'Bea' })]}
        departments={[dept([{ name: 'Atlas' }])]}
        actions={[action()]}
      />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'atl' } });
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.queryByText('Aldo')).not.toBeInTheDocument();
    expect(screen.queryByText('Dispatch a task')).not.toBeInTheDocument();
  });

  it('runs the chosen action on Enter and closes', () => {
    const run = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        onClose={onClose}
        players={[]}
        departments={[]}
        actions={[action({ run })]}
      />,
    );
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(run).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('Escape closes without running anything', () => {
    const run = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        onClose={onClose}
        players={[]}
        departments={[]}
        actions={[action({ run })]}
      />,
    );
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  it('shows a no-matches state', () => {
    render(
      <CommandPalette open onClose={() => {}} players={[]} departments={[]} actions={[action()]} />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'zzzz' } });
    expect(screen.getByText(/no matches/i)).toBeInTheDocument();
  });
});
