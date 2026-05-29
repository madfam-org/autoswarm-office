import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PermissionsPage from '../app/permissions/page';

const mockMatrix = {
  file_read: 'allow',
  file_write: 'ask',
  bash_execute: 'ask',
  git_commit: 'ask',
  git_push: 'deny',
  email_send: 'deny',
  crm_update: 'ask',
  deploy: 'deny',
  api_call: 'ask',
  pricing_proposal: 'ask',
};

function mockPermissionsFetch() {
  vi.spyOn(global, 'fetch').mockImplementation((url) => {
    const urlStr = typeof url === 'string' ? url : url.toString();

    if (urlStr.includes('/api/v1/permissions/matrix')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockMatrix),
      } as Response);
    }

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
  });
}

describe('PermissionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => {}),
    );

    render(<PermissionsPage />);
    expect(screen.getByText('Loading permissions...')).toBeInTheDocument();
  });

  it('renders the page heading and description', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('Permission Matrix')).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Configure which actions agents can perform/),
    ).toBeInTheDocument();
  });

  it('displays all action categories', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('File Read')).toBeInTheDocument();
    });

    expect(screen.getByText('File Write')).toBeInTheDocument();
    expect(screen.getByText('Bash Execute')).toBeInTheDocument();
    expect(screen.getByText('Git Commit')).toBeInTheDocument();
    expect(screen.getByText('Git Push')).toBeInTheDocument();
    expect(screen.getByText('Email Send')).toBeInTheDocument();
    expect(screen.getByText('CRM Update')).toBeInTheDocument();
    expect(screen.getByText('Deploy')).toBeInTheDocument();
    expect(screen.getByText('API Call')).toBeInTheDocument();
    expect(screen.getByText('Pricing Proposal')).toBeInTheDocument();
  });

  it('renders permission level toggle buttons', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('File Read')).toBeInTheDocument();
    });

    // 10 action categories x 3 permission levels = 30 toggle buttons
    const allowButtons = screen.getAllByRole('button', { name: /Allow/i });
    const askButtons = screen.getAllByRole('button', { name: /Ask/i });
    const denyButtons = screen.getAllByRole('button', { name: /Deny/i });

    // Filter to only permission toggle buttons (aria-label includes "Set")
    const permAllows = allowButtons.filter(
      (btn) => btn.getAttribute('aria-label')?.startsWith('Set'),
    );
    const permAsks = askButtons.filter(
      (btn) => btn.getAttribute('aria-label')?.startsWith('Set'),
    );
    const permDenys = denyButtons.filter(
      (btn) => btn.getAttribute('aria-label')?.startsWith('Set'),
    );

    expect(permAllows).toHaveLength(10);
    expect(permAsks).toHaveLength(10);
    expect(permDenys).toHaveLength(10);
  });

  it('shows "No changes" when matrix is unmodified', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('No changes')).toBeInTheDocument();
    });
  });

  it('shows "Unsaved changes" after toggling a permission', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('File Read')).toBeInTheDocument();
    });

    // Click the "Deny" button for File Read (currently set to "allow")
    const fileReadDeny = screen.getByRole('button', {
      name: 'Set File Read to Deny',
    });
    fireEvent.click(fileReadDeny);

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('resets changes when Reset button is clicked', async () => {
    mockPermissionsFetch();
    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('File Read')).toBeInTheDocument();
    });

    // Make a change
    const fileReadDeny = screen.getByRole('button', {
      name: 'Set File Read to Deny',
    });
    fireEvent.click(fileReadDeny);

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

    // Click Reset
    fireEvent.click(screen.getByText('Reset'));

    expect(screen.getByText('No changes')).toBeInTheDocument();
  });

  it('saves matrix and shows success message', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');

    // Initial load
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockMatrix),
    } as Response);

    render(<PermissionsPage />);

    await waitFor(() => {
      expect(screen.getByText('File Read')).toBeInTheDocument();
    });

    // Make a change
    const fileReadDeny = screen.getByRole('button', {
      name: 'Set File Read to Deny',
    });
    fireEvent.click(fileReadDeny);

    // Mock the save response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    // Click Save
    fireEvent.click(screen.getByText('Save Matrix'));

    await waitFor(() => {
      expect(
        screen.getByText('Permission matrix saved successfully.'),
      ).toBeInTheDocument();
    });
  });
});
