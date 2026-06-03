import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { AgentCard } from '../agent-card';
import type { Agent, AgentStatus } from '@selva/shared-types';

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    name: 'Test Agent',
    role: 'coder',
    status: 'idle',
    level: 5,
    departmentId: null,
    currentTaskId: null,
    synergyBonuses: [],
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('AgentCard', () => {
  it('renders agent name', () => {
    render(<AgentCard agent={makeAgent({ name: 'Atlas' })} />);
    expect(screen.getByText('Atlas')).toBeInTheDocument();
  });

  it('renders agent role', () => {
    render(<AgentCard agent={makeAgent({ role: 'reviewer' })} />);
    expect(screen.getByText('reviewer')).toBeInTheDocument();
  });

  it('shows correct status label for idle', () => {
    render(<AgentCard agent={makeAgent({ status: 'idle' })} />);
    expect(screen.getByText('IDLE')).toBeInTheDocument();
  });

  it('shows correct status label for working', () => {
    render(<AgentCard agent={makeAgent({ status: 'working' })} />);
    expect(screen.getByText('WORKING')).toBeInTheDocument();
  });

  it('shows correct status label for waiting_approval', () => {
    render(<AgentCard agent={makeAgent({ status: 'waiting_approval' })} />);
    expect(screen.getByText('AWAITING')).toBeInTheDocument();
  });

  it('shows correct status label for paused', () => {
    render(<AgentCard agent={makeAgent({ status: 'paused' })} />);
    expect(screen.getByText('PAUSED')).toBeInTheDocument();
  });

  it('shows correct status label for error', () => {
    render(<AgentCard agent={makeAgent({ status: 'error' })} />);
    expect(screen.getByText('ERROR')).toBeInTheDocument();
  });

  it('displays level value', () => {
    render(<AgentCard agent={makeAgent({ level: 7 })} />);
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  it('shows synergy badges when present', () => {
    const agent = makeAgent({
      synergyBonuses: [
        {
          name: 'CodeReview',
          description: 'Coder + Reviewer bonus',
          multiplier: 1.5,
          requiredRoles: ['coder', 'reviewer'],
        },
      ],
    });
    render(<AgentCard agent={agent} />);
    expect(screen.getByText('CodeReview x1.5')).toBeInTheDocument();
  });

  it('hides synergy section when synergyBonuses is empty', () => {
    render(<AgentCard agent={makeAgent({ synergyBonuses: [] })} />);
    expect(screen.queryByText(/x\d/)).not.toBeInTheDocument();
  });

  it('shows synergy multiplier value', () => {
    const agent = makeAgent({
      synergyBonuses: [
        {
          name: 'PairProg',
          description: 'Pair programming bonus',
          multiplier: 2.0,
          requiredRoles: ['coder', 'coder'],
        },
      ],
    });
    render(<AgentCard agent={agent} />);
    expect(screen.getByText('PairProg x2')).toBeInTheDocument();
  });

  it('shows role icon', () => {
    render(<AgentCard agent={makeAgent({ role: 'coder' })} />);
    // The role icon span has an aria-label matching the role
    const icon = screen.getByLabelText('coder');
    expect(icon).toBeInTheDocument();
    // Coder icon is the laptop emoji \u{1F4BB}
    expect(icon.textContent).toBe('\u{1F4BB}');
  });
});
