import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SpaceRoster } from '../SpaceRoster';
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
    name: 'Engineering',
    // Agent shape — only the fields the roster reads.
    agents: agents.map((a, i) => ({
      id: a.id ?? `a${i}`,
      name: a.name ?? `Agent${i}`,
      role: a.role ?? 'coder',
      status: a.status ?? 'idle',
    })),
  } as unknown as Department;
}

describe('SpaceRoster', () => {
  it('shows the local player as "(you)" and counts people + agents', () => {
    render(
      <SpaceRoster
        spaceName="Your Office"
        players={[player({ sessionId: 'me', name: 'Aldo' })]}
        departments={[dept([{ name: 'Atlas', status: 'working' }])]}
        localSessionId="me"
      />,
    );
    expect(screen.getByText(/Aldo \(you\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 person · 1 agent/)).toBeInTheDocument();
  });

  it('lists agent-citizens with a status label and role badge', () => {
    render(
      <SpaceRoster
        spaceName="Your Office"
        players={[]}
        departments={[
          dept([
            { name: 'Atlas', role: 'planner', status: 'working' },
            { name: 'Sage', role: 'reviewer', status: 'waiting_approval' },
          ]),
        ]}
        localSessionId="me"
      />,
    );
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('Working')).toBeInTheDocument();
    expect(screen.getByText('Awaiting approval')).toBeInTheDocument();
    expect(screen.getByText('planner')).toBeInTheDocument();
  });

  it('separates other humans from the local player', () => {
    render(
      <SpaceRoster
        spaceName="Your Office"
        players={[
          player({ sessionId: 'me', name: 'Aldo' }),
          player({ sessionId: 'other', name: 'Bea', playerStatus: 'busy' }),
        ]}
        departments={[]}
        localSessionId="me"
      />,
    );
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.getByText('Bea')).toBeInTheDocument();
    expect(screen.getByText('Busy')).toBeInTheDocument();
  });

  it('shows an inviting empty state when the office is quiet', () => {
    render(
      <SpaceRoster spaceName="Your Office" players={[]} departments={[]} localSessionId="me" />,
    );
    expect(screen.getByText(/Dispatch a task to bring an agent to life/i)).toBeInTheDocument();
  });
});
