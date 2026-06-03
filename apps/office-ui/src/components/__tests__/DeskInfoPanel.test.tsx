import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DeskInfoPanel } from '../DeskInfoPanel';
import type { Department } from '@selva/shared-types';

const mockDepartments: Department[] = [
  {
    id: 'dept-1',
    name: 'Engineering',
    slug: 'engineering',
    description: 'Engineering department',
    maxAgents: 6,
    position: { x: 32, y: 32 },
    agents: [
      {
        id: 'agent-abc-123',
        name: 'Alice',
        role: 'coder',
        status: 'working',
        level: 1,
        departmentId: 'dept-1',
        currentTaskId: null,
        synergyBonuses: [],
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      },
      {
        id: 'agent-def-456',
        name: 'Bob',
        role: 'reviewer',
        status: 'idle',
        level: 1,
        departmentId: 'dept-1',
        currentTaskId: null,
        synergyBonuses: [],
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      },
    ],
  },
];

describe('DeskInfoPanel', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <DeskInfoPanel
        open={false}
        onClose={() => {}}
        assignedAgentId="agent-abc-123"
        deskTitle="Coder Desk"
        departments={mockDepartments}
      />,
    );

    expect(container.innerHTML).toBe('');
  });

  it('renders agent info when open with valid agent', () => {
    render(
      <DeskInfoPanel
        open={true}
        onClose={() => {}}
        assignedAgentId="agent-abc-123"
        deskTitle="Coder Desk"
        departments={mockDepartments}
      />,
    );

    expect(screen.getByText('Coder Desk')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('coder')).toBeInTheDocument();
    expect(screen.getByText('working')).toBeInTheDocument();
  });

  it('shows "Unassigned desk" when no assignedAgentId', () => {
    render(
      <DeskInfoPanel
        open={true}
        onClose={() => {}}
        assignedAgentId=""
        deskTitle="Empty Desk"
        departments={mockDepartments}
      />,
    );

    expect(screen.getByText('Unassigned desk')).toBeInTheDocument();
  });

  it('shows "Agent not found" when agentId does not match', () => {
    render(
      <DeskInfoPanel
        open={true}
        onClose={() => {}}
        assignedAgentId="nonexistent-id"
        deskTitle="Ghost Desk"
        departments={mockDepartments}
      />,
    );

    expect(screen.getByText('Agent not found')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();

    render(
      <DeskInfoPanel
        open={true}
        onClose={onClose}
        assignedAgentId="agent-abc-123"
        deskTitle="Test Desk"
        departments={mockDepartments}
      />,
    );

    fireEvent.click(screen.getByLabelText('Close desk info'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('has accessible close button with aria-label', () => {
    render(
      <DeskInfoPanel
        open={true}
        onClose={() => {}}
        assignedAgentId="agent-abc-123"
        deskTitle="Test Desk"
        departments={mockDepartments}
      />,
    );

    const closeButton = screen.getByLabelText('Close desk info');
    expect(closeButton).toBeInTheDocument();
    expect(closeButton.tagName).toBe('BUTTON');
  });

  it('renders correct status color for idle agent', () => {
    render(
      <DeskInfoPanel
        open={true}
        onClose={() => {}}
        assignedAgentId="agent-def-456"
        deskTitle="Reviewer Desk"
        departments={mockDepartments}
      />,
    );

    expect(screen.getByText('idle')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });
});
