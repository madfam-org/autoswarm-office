import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApprovalPanel } from '../ApprovalPanel';
import type { ApprovalRequest } from '@selva/shared-types';

// Mock gameEventBus to avoid Phaser dependency
vi.mock('../../game/PhaserGame', () => ({
  gameEventBus: {
    emit: vi.fn(),
    on: vi.fn(() => vi.fn()),
  },
}));

const mockRequest: ApprovalRequest = {
  id: 'req-1',
  agentId: 'agent-1',
  agentName: 'Nova',
  actionCategory: 'file_write',
  actionType: 'write_file',
  payload: {},
  reasoning: 'Need to write the implementation file for the auth module',
  urgency: 'medium',
  createdAt: new Date().toISOString(),
};

const mockCriticalRequest: ApprovalRequest = {
  id: 'req-2',
  agentId: 'agent-2',
  agentName: 'Atlas',
  actionCategory: 'deploy',
  actionType: 'deploy_production',
  payload: {},
  diff: '--- a/config.yml\n+++ b/config.yml\n@@ -1 +1 @@\n-replicas: 2\n+replicas: 4',
  reasoning: 'Scaling production deployment to handle increased traffic',
  urgency: 'critical',
  createdAt: new Date(Date.now() - 60000).toISOString(),
};

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof ApprovalPanel>> = {},
) {
  const defaults = {
    open: true,
    onClose: vi.fn(),
    pendingApprovals: [] as ApprovalRequest[],
    onApprove: vi.fn().mockResolvedValue(true),
    onDeny: vi.fn().mockResolvedValue(true),
    connected: true,
    ...overrides,
  };
  return { ...render(<ApprovalPanel {...defaults} />), props: defaults };
}

describe('ApprovalPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders with title when open', () => {
    renderPanel();
    expect(screen.getByText('Approval Queue')).toBeInTheDocument();
  });

  it('returns null when closed', () => {
    renderPanel({ open: false });
    expect(screen.queryByText('Approval Queue')).not.toBeInTheDocument();
  });

  it('shows empty state when no pending approvals', () => {
    renderPanel();
    expect(screen.getByText('No pending approvals')).toBeInTheDocument();
  });

  it('renders request cards with agent name, action tag, urgency badge', () => {
    renderPanel({ pendingApprovals: [mockRequest] });
    expect(screen.getByText('Nova')).toBeInTheDocument();
    expect(screen.getByText('[W]')).toBeInTheDocument();
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('expands card on click to show full reasoning', () => {
    renderPanel({ pendingApprovals: [mockRequest] });

    // Click the expand button (contains agent name)
    const expandBtn = screen.getByRole('button', { expanded: false });
    fireEvent.click(expandBtn);

    // After click, full reasoning visible in the expanded section
    expect(
      screen.getByText(mockRequest.reasoning),
    ).toBeInTheDocument();
  });

  it('calls onApprove with requestId when Approve button clicked', () => {
    const { props } = renderPanel({ pendingApprovals: [mockRequest] });

    const approveBtn = screen.getByText('Approve');
    fireEvent.click(approveBtn);

    expect(props.onApprove).toHaveBeenCalledWith('req-1', undefined);
  });

  it('calls onDeny with requestId when Deny button clicked', () => {
    const { props } = renderPanel({ pendingApprovals: [mockRequest] });

    const denyBtn = screen.getByText('Deny');
    fireEvent.click(denyBtn);

    expect(props.onDeny).toHaveBeenCalledWith('req-1', undefined);
  });

  it('calls onClose when ESC pressed', () => {
    const { props } = renderPanel();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalled();
  });

  it('sorts by urgency with critical first', () => {
    renderPanel({
      pendingApprovals: [mockRequest, mockCriticalRequest],
    });

    const agentNames = screen.getAllByText(/^(Nova|Atlas)$/);
    // Atlas (critical) should appear before Nova (medium)
    expect(agentNames[0].textContent).toBe('Atlas');
    expect(agentNames[1].textContent).toBe('Nova');
  });

  it('shows error toast when onApprove returns false', async () => {
    const { props } = renderPanel({
      pendingApprovals: [mockRequest],
      onApprove: vi.fn().mockResolvedValue(false),
    });

    const approveBtn = screen.getByText('Approve');
    await fireEvent.click(approveBtn);

    // onApprove was called
    expect(props.onApprove).toHaveBeenCalledWith('req-1', undefined);
  });

  it('shows connection status indicator', () => {
    const { rerender } = render(
      <ApprovalPanel
        open={true}
        onClose={vi.fn()}
        pendingApprovals={[]}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
        connected={true}
      />,
    );

    expect(screen.getByLabelText('Connected')).toBeInTheDocument();

    rerender(
      <ApprovalPanel
        open={true}
        onClose={vi.fn()}
        pendingApprovals={[]}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
        connected={false}
      />,
    );

    expect(screen.getByLabelText('Disconnected')).toBeInTheDocument();
  });
});
