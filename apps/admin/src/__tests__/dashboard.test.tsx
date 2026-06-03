import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AdminDashboard from '../app/page';

const mockAgents = [
  {
    id: 'a1',
    name: 'Coder-Alpha',
    role: 'coder',
    status: 'idle',
    departmentId: 'd1',
    level: 3,
    skill_ids: [],
  },
  {
    id: 'a2',
    name: 'Researcher-Alpha',
    role: 'researcher',
    status: 'working',
    departmentId: 'd2',
    level: 2,
    skill_ids: [],
  },
  {
    id: 'a3',
    name: 'Coder-Beta',
    role: 'coder',
    status: 'idle',
    departmentId: 'd1',
    level: 4,
    skill_ids: [],
  },
];

const mockDepartments = [
  { id: 'd1', name: 'Engineering', slug: 'engineering' },
  { id: 'd2', name: 'Research', slug: 'research' },
];

const mockPendingApprovals = { count: 5 };

const mockTokens = {
  dailyLimit: 10000,
  used: 2500,
  remaining: 7500,
  resetAt: '2026-03-16T00:00:00Z',
};

function mockFetchResponses() {
  vi.spyOn(global, 'fetch').mockImplementation((url) => {
    const urlStr = typeof url === 'string' ? url : url.toString();

    if (urlStr.includes('/api/v1/agents')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockAgents),
      } as Response);
    }
    if (urlStr.includes('/api/v1/departments')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockDepartments),
      } as Response);
    }
    if (urlStr.includes('/api/v1/approvals/pending')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockPendingApprovals),
      } as Response);
    }
    if (urlStr.includes('/api/v1/billing/tokens')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTokens),
      } as Response);
    }

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);
  });
}

describe('AdminDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => {}), // never resolves
    );

    render(<AdminDashboard />);
    expect(screen.getByText('Loading dashboard...')).toBeInTheDocument();
  });

  it('renders the page heading', async () => {
    mockFetchResponses();
    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Selva Admin')).toBeInTheDocument();
    });
  });

  it('displays stat cards with correct data after fetch', async () => {
    mockFetchResponses();
    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Total Agents')).toBeInTheDocument();
    });

    // 3 agents, 2 departments, 5 pending approvals -- all distinct values
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Departments')).toBeInTheDocument();
    expect(screen.getByText('Pending Approvals')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Compute Tokens')).toBeInTheDocument();
    expect(screen.getByText('7,500')).toBeInTheDocument();
  });

  it('renders navigation links for sub-pages', async () => {
    mockFetchResponses();
    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Agents')).toBeInTheDocument();
    });

    expect(screen.getByText('Permissions')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Health')).toBeInTheDocument();

    // Verify link descriptions
    expect(screen.getByText('Manage AI agents')).toBeInTheDocument();
    expect(screen.getByText('Configure permission matrix')).toBeInTheDocument();
    expect(screen.getByText('System status')).toBeInTheDocument();
  });

  it('shows error message when fetch fails', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(
      new Error('Network unreachable'),
    );

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText(/Network unreachable/)).toBeInTheDocument();
    });
  });

  it('shows token usage bar with correct percentage styling', async () => {
    mockFetchResponses();
    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Compute Tokens')).toBeInTheDocument();
    });

    // 2500/10000 = 25% -- should use emerald (green) bar
    expect(screen.getByText('2,500 / 10,000 used')).toBeInTheDocument();
  });
});
