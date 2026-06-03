import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ApprovalModal } from '../approval-modal';
import type { ApprovalRequest } from '@selva/shared-types';

function makeRequest(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    id: 'req-1',
    agentId: 'agent-1',
    agentName: 'Atlas',
    actionCategory: 'file_write',
    actionType: 'create',
    payload: {},
    reasoning: 'Need to create a config file for deployment.',
    urgency: 'medium',
    createdAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderModal(
  props: Partial<React.ComponentProps<typeof ApprovalModal>> = {},
) {
  const defaults = {
    open: true,
    onOpenChange: vi.fn(),
    request: makeRequest(),
    onApprove: vi.fn(),
    onDeny: vi.fn(),
  };
  const merged = { ...defaults, ...props };
  return { ...render(<ApprovalModal {...merged} />), ...merged };
}

describe('ApprovalModal', () => {
  it('renders agent name', () => {
    renderModal({ request: makeRequest({ agentName: 'Nova' }) });
    expect(screen.getByText('Nova')).toBeInTheDocument();
  });

  it('renders action category and type', () => {
    renderModal({
      request: makeRequest({ actionCategory: 'git_push', actionType: 'force' }),
    });
    expect(screen.getByText('git_push / force')).toBeInTheDocument();
  });

  it('renders urgency badge', () => {
    renderModal({ request: makeRequest({ urgency: 'critical' }) });
    expect(screen.getByText('critical')).toBeInTheDocument();
  });

  it('renders reasoning text', () => {
    renderModal({
      request: makeRequest({ reasoning: 'Deploying hotfix to production.' }),
    });
    expect(
      screen.getByText('Deploying hotfix to production.'),
    ).toBeInTheDocument();
  });

  it('shows diff block when diff is present', () => {
    renderModal({
      request: makeRequest({ diff: '+ added line\n- removed line' }),
    });
    expect(screen.getByText('Diff')).toBeInTheDocument();
    expect(
      screen.getByText((content) => content.includes('+ added line')),
    ).toBeInTheDocument();
  });

  it('does not show diff block when diff is absent', () => {
    renderModal({ request: makeRequest({ diff: undefined }) });
    expect(screen.queryByText('Diff')).not.toBeInTheDocument();
  });

  it('calls onApprove with requestId and feedback', () => {
    const onApprove = vi.fn();
    renderModal({
      onApprove,
      request: makeRequest({ id: 'req-42' }),
    });

    const textarea = screen.getByPlaceholderText('Add notes for the agent...');
    fireEvent.change(textarea, { target: { value: 'Looks good' } });
    fireEvent.click(screen.getByText('Approve'));

    expect(onApprove).toHaveBeenCalledWith('req-42', 'Looks good');
  });

  it('calls onDeny with requestId and feedback', () => {
    const onDeny = vi.fn();
    renderModal({
      onDeny,
      request: makeRequest({ id: 'req-99' }),
    });

    const textarea = screen.getByPlaceholderText('Add notes for the agent...');
    fireEvent.change(textarea, { target: { value: 'Too risky' } });
    fireEvent.click(screen.getByText('Deny'));

    expect(onDeny).toHaveBeenCalledWith('req-99', 'Too risky');
  });

  it('allows typing feedback', () => {
    renderModal();
    const textarea = screen.getByPlaceholderText('Add notes for the agent...');
    fireEvent.change(textarea, { target: { value: 'Some feedback text' } });
    expect(textarea).toHaveValue('Some feedback text');
  });

  it('calls onOpenChange when close button clicked', () => {
    const onOpenChange = vi.fn();
    renderModal({ onOpenChange });
    fireEvent.click(screen.getByLabelText('Close'));
    expect(onOpenChange).toHaveBeenCalled();
  });

  it('renders "Approval Required" title', () => {
    renderModal();
    expect(screen.getByText('Approval Required')).toBeInTheDocument();
  });

  it('has Approve and Deny buttons present', () => {
    renderModal();
    expect(screen.getByText('Approve')).toBeInTheDocument();
    expect(screen.getByText('Deny')).toBeInTheDocument();
  });
});
