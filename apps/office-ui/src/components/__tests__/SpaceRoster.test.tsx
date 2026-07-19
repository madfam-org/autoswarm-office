import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

/**
 * Mimics a Colyseus ArraySchema: iterable and has .length/.forEach like a
 * real array, but deliberately fails Array.isArray() — exactly like the
 * live proxy `dept.agents` can be depending on how state reached this
 * component. Array.prototype.flatMap does NOT flatten a returned value
 * that fails Array.isArray(); it pushes it as a single element instead.
 */
function arraySchemaLike<T>(items: T[]): T[] {
  const obj = {
    length: items.length,
    forEach: (cb: (v: T, i: number) => void) => items.forEach(cb),
    [Symbol.iterator]: () => items[Symbol.iterator](),
  };
  return obj as unknown as T[];
}

function deptWithArraySchemaAgents(
  agents: Array<Partial<{ id: string; name: string; role: string; status: string }>>,
): Department {
  const real = dept(agents);
  return { ...real, agents: arraySchemaLike(real.agents) } as Department;
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

  it('flattens agents when dept.agents is a Colyseus ArraySchema (not a real Array)', () => {
    // Regression test: dept.agents.flatMap((d) => d.agents ?? []) silently
    // fails to flatten when d.agents is array-like-but-not-Array.isArray()
    // (a live Colyseus ArraySchema proxy) — flatMap treats the whole proxy
    // as one opaque element instead of spreading its items, so every agent
    // field renders blank. The fix wraps each dept.agents in Array.from()
    // before flatMap. See feedback_dockerfile_workspace_dep_build_filter-
    // adjacent lesson: this shipped in PR #240 undetected because plain-
    // array test fixtures never exercised the ArraySchema shape.
    render(
      <SpaceRoster
        spaceName="Your Office"
        players={[]}
        departments={[deptWithArraySchemaAgents([{ name: 'Atlas', role: 'planner', status: 'working' }])]}
        localSessionId="me"
      />,
    );
    expect(screen.getByText('1 agent', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('planner')).toBeInTheDocument();
    expect(screen.getByText('Working')).toBeInTheDocument();
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

  describe('wave (E1 wave-to-walk-over)', () => {
    it('hides the wave affordance when onWave is not provided', () => {
      render(
        <SpaceRoster
          spaceName="Your Office"
          players={[player({ sessionId: 'me', name: 'Aldo' }), player({ sessionId: 'other', name: 'Bea' })]}
          departments={[dept([{ name: 'Atlas' }])]}
          localSessionId="me"
        />,
      );
      expect(screen.queryByRole('button', { name: /Wave at/i })).not.toBeInTheDocument();
    });

    it('waves at another human with kind "player" and their sessionId', () => {
      const onWave = vi.fn();
      render(
        <SpaceRoster
          spaceName="Your Office"
          players={[
            player({ sessionId: 'me', name: 'Aldo' }),
            player({ sessionId: 'other-1', name: 'Bea' }),
          ]}
          departments={[]}
          localSessionId="me"
          onWave={onWave}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: 'Wave at Bea' }));
      expect(onWave).toHaveBeenCalledWith({ kind: 'player', id: 'other-1' });
    });

    it('waves at an agent-citizen with kind "agent" and their id', () => {
      const onWave = vi.fn();
      render(
        <SpaceRoster
          spaceName="Your Office"
          players={[]}
          departments={[dept([{ id: 'agent-42', name: 'Atlas' }])]}
          localSessionId="me"
          onWave={onWave}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: 'Wave at Atlas' }));
      expect(onWave).toHaveBeenCalledWith({ kind: 'agent', id: 'agent-42' });
    });

    it('does not trigger onSelectPlayer when waving at a selectable human row', () => {
      // Regression guard: the wave button must be a SIBLING of the row's own
      // <button onClick={onSelectPlayer}>, never nested inside it — nesting
      // would either be invalid HTML or double-fire both handlers on click.
      const onWave = vi.fn();
      const onSelectPlayer = vi.fn();
      render(
        <SpaceRoster
          spaceName="Your Office"
          players={[
            player({ sessionId: 'me', name: 'Aldo' }),
            player({ sessionId: 'other-1', name: 'Bea' }),
          ]}
          departments={[]}
          localSessionId="me"
          onWave={onWave}
          onSelectPlayer={onSelectPlayer}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: 'Wave at Bea' }));
      expect(onWave).toHaveBeenCalledWith({ kind: 'player', id: 'other-1' });
      expect(onSelectPlayer).not.toHaveBeenCalled();
    });
  });
});
