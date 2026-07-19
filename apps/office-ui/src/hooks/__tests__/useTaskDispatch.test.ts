import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useTaskDispatch } from '../../hooks/useTaskDispatch';
import * as api from '@/lib/api';

describe('useTaskDispatch', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts with idle status and null error', () => {
    const { result } = renderHook(() => useTaskDispatch());

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.lastDispatchedTask).toBeNull();
  });

  it('dispatch() transitions idle -> submitting -> success', async () => {
    const mockResponse = {
      id: 'task-123',
      description: 'Fix bug',
      graph_type: 'coding',
      status: 'queued',
      assigned_agent_ids: [],
      created_at: '2025-01-01T00:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      const response = await result.current.dispatch({
        description: 'Fix bug',
        graph_type: 'coding',
      });
      expect(response).toEqual(mockResponse);
    });

    expect(result.current.status).toBe('success');
    expect(result.current.lastDispatchedTask).toEqual(mockResponse);
  });

  it('dispatch() transitions idle -> submitting -> error on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: 'Validation error' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      const response = await result.current.dispatch({
        description: 'Bad request',
        graph_type: 'coding',
      });
      expect(response).toBeNull();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('Validation error');
  });

  it('dispatch() sets limitReached on a 402 budget_exhausted (the upgrade moment)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({
        detail: { code: 'budget_exhausted', message: "You've hit today's compute budget." },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      const response = await result.current.dispatch({
        description: 'Over budget',
        graph_type: 'coding',
      });
      expect(response).toBeNull();
    });

    expect(result.current.limitReached).toBe(true);
    expect(result.current.limitMessage).toMatch(/compute budget/i);
    // A budget 402 is the upgrade moment, not a generic error banner.
    expect(result.current.error).toBeNull();
  });

  it('dispatch() treats a plain 402 (no code) as a generic error, not the modal', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: 'some other payment issue' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      await result.current.dispatch({ description: 'x', graph_type: 'coding' });
    });

    expect(result.current.limitReached).toBe(false);
    expect(result.current.error).toBe('some other payment issue');
  });

  it('dispatch() handles network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Network down'));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      const response = await result.current.dispatch({
        description: 'Offline test',
        graph_type: 'research',
      });
      expect(response).toBeNull();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('Network error — could not reach server');
  });

  it('stores lastDispatchedTask on success', async () => {
    const mockResponse = {
      id: 'task-456',
      description: 'Deploy app',
      graph_type: 'sequential',
      status: 'queued',
      assigned_agent_ids: ['agent-1'],
      created_at: '2025-01-01T00:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      await result.current.dispatch({
        description: 'Deploy app',
        graph_type: 'sequential',
      });
    });

    expect(result.current.lastDispatchedTask).toEqual(mockResponse);
  });

  it('reset() clears to idle', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'task-789',
        description: 'Test',
        graph_type: 'coding',
        status: 'queued',
        assigned_agent_ids: [],
        created_at: '2025-01-01T00:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      await result.current.dispatch({
        description: 'Test',
        graph_type: 'coding',
      });
    });
    expect(result.current.status).toBe('success');

    act(() => {
      result.current.reset();
    });

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.lastDispatchedTask).toBeNull();
  });

  it('sends correct URL and request body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'task-x',
        description: 'Test body',
        graph_type: 'research',
        status: 'queued',
        assigned_agent_ids: ['agent-1'],
        created_at: '2025-01-01T00:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      await result.current.dispatch({
        description: 'Test body',
        graph_type: 'research',
        assigned_agent_ids: ['agent-1'],
        required_skills: ['coding'],
        payload: { key: 'value' },
      });
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:4300/api/v1/swarms/dispatch',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          description: 'Test body',
          graph_type: 'research',
          assigned_agent_ids: ['agent-1'],
          required_skills: ['coding'],
          payload: { key: 'value' },
        }),
        credentials: 'include',
      }),
    );
  });

  it('returns mock response in demo mode without fetching', async () => {
    vi.spyOn(api, 'isDemo').mockReturnValue(true);
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      const response = await result.current.dispatch({
        description: 'Demo dispatch',
        graph_type: 'coding',
      });
      expect(response).not.toBeNull();
      expect(response?.id).toMatch(/^demo-task-/);
      expect(response?.description).toBe('Demo dispatch');
    });

    expect(result.current.status).toBe('success');
    // Fetch should NOT have been called
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('includes credentials: include', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'task-creds',
        description: 'Creds test',
        graph_type: 'coding',
        status: 'queued',
        assigned_agent_ids: [],
        created_at: '2025-01-01T00:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTaskDispatch());

    await act(async () => {
      await result.current.dispatch({
        description: 'Creds test',
        graph_type: 'coding',
      });
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        credentials: 'include',
      }),
    );
  });
});
