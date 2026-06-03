import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SimplifiedView } from '../SimplifiedView';
import type { Department, ApprovalRequest, ChatMessage } from '@selva/shared-types';

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
        id: 'agent-1',
        name: 'Nova',
        role: 'coder',
        status: 'working',
        level: 1,
        departmentId: 'dept-1',
        currentTaskId: 'task-abc',
        currentNodeId: 'implement',
        synergyBonuses: [],
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      },
      {
        id: 'agent-2',
        name: 'Atlas',
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
  {
    id: 'dept-2',
    name: 'Research',
    slug: 'research',
    description: 'Research department',
    maxAgents: 4,
    position: { x: 928, y: 544 },
    agents: [
      {
        id: 'agent-3',
        name: 'Sage',
        role: 'researcher',
        status: 'waiting_approval',
        level: 1,
        departmentId: 'dept-2',
        currentTaskId: 'task-def',
        synergyBonuses: [],
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      },
    ],
  },
];

const mockApprovals: ApprovalRequest[] = [
  {
    id: 'req-1',
    agentId: 'agent-3',
    agentName: 'Sage',
    actionCategory: 'file_write',
    actionType: 'write_file',
    payload: {},
    reasoning: 'Need to write research findings to output file',
    urgency: 'medium',
    createdAt: new Date().toISOString(),
  },
];

const mockChatMessages: ChatMessage[] = [
  {
    id: 'msg-1',
    senderSessionId: 'session-1',
    senderName: 'Alice',
    content: 'Hello everyone!',
    timestamp: Date.now() - 60000,
    isSystem: false,
  },
  {
    id: 'msg-2',
    senderSessionId: '',
    senderName: 'System',
    content: 'Bob joined the room',
    timestamp: Date.now() - 30000,
    isSystem: true,
  },
];

function renderView(
  overrides: Partial<React.ComponentProps<typeof SimplifiedView>> = {},
) {
  const defaults = {
    departments: [] as Department[],
    pendingApprovals: [] as ApprovalRequest[],
    chatMessages: [] as ChatMessage[],
    onSendChat: vi.fn(),
    onApprove: vi.fn().mockResolvedValue(true),
    onDeny: vi.fn().mockResolvedValue(true),
    onDispatchTask: vi.fn(),
    onOpenMarketplace: vi.fn(),
    onToggleViewMode: vi.fn(),
    colyseusConnected: true,
    approvalsConnected: true,
    ...overrides,
  };
  return { ...render(<SimplifiedView {...defaults} />), props: defaults };
}

describe('SimplifiedView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders departments with agent list', () => {
    renderView({ departments: mockDepartments });

    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    expect(screen.getByText('Nova')).toBeInTheDocument();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('Sage')).toBeInTheDocument();
  });

  it('renders agents with status indicators', () => {
    renderView({ departments: mockDepartments });

    // Check status dots exist via aria-labels
    expect(screen.getByLabelText('Working')).toBeInTheDocument();
    expect(screen.getByLabelText('Idle')).toBeInTheDocument();
    expect(screen.getByLabelText('Awaiting Approval')).toBeInTheDocument();
  });

  it('renders approval queue with approve and deny buttons', () => {
    renderView({ pendingApprovals: mockApprovals });

    expect(screen.getByText('Sage')).toBeInTheDocument();
    expect(screen.getByText('file_write')).toBeInTheDocument();
    expect(screen.getByLabelText('Approve action by Sage')).toBeInTheDocument();
    expect(screen.getByLabelText('Deny action by Sage')).toBeInTheDocument();
  });

  it('calls onApprove when approve button is clicked', () => {
    const { props } = renderView({ pendingApprovals: mockApprovals });

    fireEvent.click(screen.getByLabelText('Approve action by Sage'));
    expect(props.onApprove).toHaveBeenCalledWith('req-1');
  });

  it('calls onDeny when deny button is clicked', () => {
    const { props } = renderView({ pendingApprovals: mockApprovals });

    fireEvent.click(screen.getByLabelText('Deny action by Sage'));
    expect(props.onDeny).toHaveBeenCalledWith('req-1');
  });

  it('renders chat messages', () => {
    renderView({ chatMessages: mockChatMessages });

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Hello everyone!')).toBeInTheDocument();
    expect(screen.getByText('Bob joined the room')).toBeInTheDocument();
  });

  it('sends chat message on Enter key in input', () => {
    const { props } = renderView();

    const input = screen.getByPlaceholderText('Type a message...');
    fireEvent.change(input, { target: { value: 'Test message' } });
    fireEvent.submit(input.closest('form')!);

    expect(props.onSendChat).toHaveBeenCalledWith('Test message');
  });

  it('renders new task button that calls onDispatchTask', () => {
    const { props } = renderView();

    const button = screen.getByText('+ New Task');
    fireEvent.click(button);

    expect(props.onDispatchTask).toHaveBeenCalled();
  });

  it('has accessible landmarks and labels', () => {
    renderView({ departments: mockDepartments, pendingApprovals: mockApprovals });

    // role="main" on root
    expect(screen.getByRole('main')).toBeInTheDocument();

    // Section labels
    expect(screen.getByLabelText('Departments')).toBeInTheDocument();
    expect(screen.getByLabelText('Pending Approvals')).toBeInTheDocument();
    expect(screen.getByLabelText('Chat')).toBeInTheDocument();
    expect(screen.getByLabelText('Chat messages')).toBeInTheDocument();

    // Department article labels
    expect(screen.getByLabelText('Engineering department')).toBeInTheDocument();
    expect(screen.getByLabelText('Research department')).toBeInTheDocument();
  });

  it('renders empty state when no departments', () => {
    renderView({ departments: [] });

    expect(screen.getByText('No departments available')).toBeInTheDocument();
  });

  it('renders empty state for approvals when none pending', () => {
    renderView({ pendingApprovals: [] });

    expect(screen.getByText('No pending approvals')).toBeInTheDocument();
  });

  it('renders game view toggle button', () => {
    const { props } = renderView();

    const toggle = screen.getByLabelText('Switch to game view');
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveTextContent('Game View');

    fireEvent.click(toggle);
    expect(props.onToggleViewMode).toHaveBeenCalled();
  });

  it('shows connection status indicators', () => {
    renderView({ colyseusConnected: true, approvalsConnected: false });

    expect(screen.getByLabelText('Room connected')).toBeInTheDocument();
    expect(screen.getByLabelText('API disconnected')).toBeInTheDocument();
  });

  it('shows current node id for working agents', () => {
    renderView({ departments: mockDepartments });

    // Nova is working with currentNodeId='implement'
    expect(screen.getByText('[implement]')).toBeInTheDocument();
  });

  it('renders skills button when onOpenMarketplace is provided', () => {
    const { props } = renderView({ onOpenMarketplace: vi.fn() });

    const skillsButton = screen.getByText('Skills');
    fireEvent.click(skillsButton);

    expect(props.onOpenMarketplace).toHaveBeenCalled();
  });
});
