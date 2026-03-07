import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TaskDispatchPanel } from '../TaskDispatchPanel';
import type { DispatchRequest, DispatchResponse, DispatchStatus } from '../../hooks/useTaskDispatch';

// Mock gameEventBus to avoid Phaser dependency
vi.mock('../../game/PhaserGame', () => ({
  gameEventBus: {
    emit: vi.fn(),
    on: vi.fn(() => vi.fn()),
  },
}));

function renderPanel(overrides: Partial<React.ComponentProps<typeof TaskDispatchPanel>> = {}) {
  const defaults = {
    open: true,
    onClose: vi.fn(),
    onDispatch: vi.fn().mockResolvedValue(null),
    status: 'idle' as DispatchStatus,
    error: null,
    lastDispatchedTask: null,
    departments: [],
    onReset: vi.fn(),
    ...overrides,
  };
  return { ...render(<TaskDispatchPanel {...defaults} />), props: defaults };
}

describe('TaskDispatchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders when open', () => {
    renderPanel();
    expect(screen.getByText('Dispatch Task')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Describe the task...')).toBeInTheDocument();
  });

  it('does not render when closed', () => {
    renderPanel({ open: false });
    expect(screen.queryByText('Dispatch Task')).not.toBeInTheDocument();
  });

  it('renders all graph type buttons', () => {
    renderPanel();
    expect(screen.getByText('coding')).toBeInTheDocument();
    expect(screen.getByText('research')).toBeInTheDocument();
    expect(screen.getByText('crm')).toBeInTheDocument();
    expect(screen.getByText('sequential')).toBeInTheDocument();
    expect(screen.getByText('parallel')).toBeInTheDocument();
  });

  it('calls onDispatch with form values on submit', async () => {
    const onDispatch = vi.fn().mockResolvedValue({
      id: 'task-1',
      description: 'Test task',
      graph_type: 'coding',
      status: 'queued',
      assigned_agent_ids: [],
      created_at: '2025-01-01T00:00:00Z',
    } satisfies DispatchResponse);

    renderPanel({ onDispatch });

    const textarea = screen.getByPlaceholderText('Describe the task...');
    fireEvent.change(textarea, { target: { value: 'Fix the login bug' } });

    const codingBtn = screen.getByText('coding');
    fireEvent.click(codingBtn);

    const submitBtn = screen.getByText('Dispatch');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(onDispatch).toHaveBeenCalledWith(
        expect.objectContaining({
          description: 'Fix the login bug',
          graph_type: 'coding',
        } satisfies Partial<DispatchRequest>),
      );
    });
  });

  it('disables submit when description is empty', () => {
    renderPanel();
    const submitBtn = screen.getByText('Dispatch');
    expect(submitBtn).toBeDisabled();
  });

  it('disables submit when status is submitting', () => {
    renderPanel({ status: 'submitting' });

    // Fill in description so only the status check matters
    const textarea = screen.getByPlaceholderText('Describe the task...');
    fireEvent.change(textarea, { target: { value: 'Something' } });

    const submitBtn = screen.getByRole('button', { name: /dispatching/i });
    expect(submitBtn).toBeDisabled();
  });

  it('shows error message when error prop is set', () => {
    renderPanel({ error: 'Server is down' });
    expect(screen.getByText('Server is down')).toBeInTheDocument();
  });

  it('shows success message with task ID', () => {
    renderPanel({
      status: 'success',
      lastDispatchedTask: {
        id: 'abc12345-6789-0000-0000-000000000000',
        description: 'Done',
        graph_type: 'coding',
        status: 'queued',
        assigned_agent_ids: [],
        created_at: '2025-01-01T00:00:00Z',
      },
    });
    expect(screen.getByText('Task queued: abc12345')).toBeInTheDocument();
  });

  it('calls onClose when ESC button clicked', () => {
    const { props } = renderPanel();
    const escBtn = screen.getByLabelText('Close dispatch panel');
    fireEvent.click(escBtn);
    expect(props.onClose).toHaveBeenCalled();
  });

  it('shows department agents when agent section expanded', () => {
    renderPanel({
      departments: [
        {
          id: 'dept-1',
          name: 'Engineering',
          slug: 'engineering',
          maxAgents: 6,
          agents: [
            {
              id: 'agent-1',
              name: 'Ada',
              role: 'coder',
              status: 'idle',
              level: 1,
              currentTaskId: null,
              synergyBonuses: [],
            },
          ],
        },
      ] as any,
    });

    // Expand agents section
    const expandBtn = screen.getByText(/Assign Agents/);
    fireEvent.click(expandBtn);

    expect(screen.getByText('Ada')).toBeInTheDocument();
    expect(screen.getByText(/coder/)).toBeInTheDocument();
  });

  it('shows character count for description', () => {
    renderPanel();
    expect(screen.getByText('0/2000')).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText('Describe the task...');
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    expect(screen.getByText('5/2000')).toBeInTheDocument();
  });
});
