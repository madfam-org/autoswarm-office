import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useApprovals } from '../../hooks/useApprovals';

// ---------------------------------------------------------------------------
// MockWebSocket
// ---------------------------------------------------------------------------

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  CONNECTING = 0;
  OPEN = 1;
  CLOSING = 2;
  CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static instances: MockWebSocket[] = [];

  static reset() {
    MockWebSocket.instances = [];
  }

  static get last(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  simulateMessage(data: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }

  simulateClose(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code } as CloseEvent);
  }

  simulateError() {
    this.onerror?.(new Event('error'));
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeApprovalRequest(id: string) {
  return {
    id,
    agentId: 'agent-1',
    agentName: 'TestAgent',
    actionCategory: 'file_read' as const,
    actionType: 'read',
    payload: {},
    reasoning: 'Testing',
    urgency: 'medium' as const,
    createdAt: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe('useApprovals', () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('fetch', vi.fn());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  // -----------------------------------------------------------------------
  // Connection lifecycle
  // -----------------------------------------------------------------------

  it('starts with empty pendingApprovals and connected=false', () => {
    const { result } = renderHook(() => useApprovals());

    expect(result.current.pendingApprovals).toEqual([]);
    expect(result.current.connected).toBe(false);
  });

  it('sets connected=true when WebSocket fires onopen', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    expect(result.current.connected).toBe(true);
  });

  it('sets connected=false on WebSocket close', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });
    expect(result.current.connected).toBe(true);

    act(() => {
      ws.simulateClose(1000);
    });
    expect(result.current.connected).toBe(false);
  });

  it('sets connected=false on WebSocket error', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });
    expect(result.current.connected).toBe(true);

    act(() => {
      ws.simulateError();
    });
    expect(result.current.connected).toBe(false);
  });

  // -----------------------------------------------------------------------
  // Message handling
  // -----------------------------------------------------------------------

  it('adds to pendingApprovals on approval_request message', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    const request = makeApprovalRequest('req-1');
    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: request });
    });

    expect(result.current.pendingApprovals).toHaveLength(1);
    expect(result.current.pendingApprovals[0].id).toBe('req-1');
  });

  it('removes from pendingApprovals on approval_resolved message', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    const request = makeApprovalRequest('req-1');
    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: request });
    });
    expect(result.current.pendingApprovals).toHaveLength(1);

    act(() => {
      ws.simulateMessage({
        type: 'approval_resolved',
        payload: { requestId: 'req-1', result: 'approved', respondedAt: new Date().toISOString() },
      });
    });

    expect(result.current.pendingApprovals).toHaveLength(0);
  });

  it('replaces pendingApprovals on approval_batch message', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    // Add one first via individual message
    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: makeApprovalRequest('old-1') });
    });
    expect(result.current.pendingApprovals).toHaveLength(1);

    // Batch replaces everything
    const batch = [makeApprovalRequest('batch-1'), makeApprovalRequest('batch-2')];
    act(() => {
      ws.simulateMessage({ type: 'approval_batch', payload: batch });
    });

    expect(result.current.pendingApprovals).toHaveLength(2);
    expect(result.current.pendingApprovals.map((a) => a.id)).toEqual(['batch-1', 'batch-2']);
  });

  it('deduplicates requests with the same id', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    const request = makeApprovalRequest('dup-1');
    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: request });
      ws.simulateMessage({ type: 'approval_request', payload: request });
    });

    expect(result.current.pendingApprovals).toHaveLength(1);
  });

  it('responds to ping with pong', () => {
    renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateMessage({ type: 'ping' });
    });

    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'pong' }));
  });

  it('ignores malformed messages without crashing', () => {
    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    // Send raw non-JSON via onmessage
    act(() => {
      ws.onmessage?.(new MessageEvent('message', { data: 'not json' }));
    });

    expect(result.current.pendingApprovals).toEqual([]);
    expect(result.current.connected).toBe(true);
  });

  // -----------------------------------------------------------------------
  // approve / deny actions
  // -----------------------------------------------------------------------

  it('approve() calls fetch with correct URL and method', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: makeApprovalRequest('req-a') });
    });

    await act(async () => {
      result.current.approve('req-a', 'looks good');
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:4300/api/v1/approvals/req-a/approve',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback: 'looks good' }),
        credentials: 'include',
      }),
    );
  });

  it('deny() calls fetch with correct URL and method', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: makeApprovalRequest('req-b') });
    });

    await act(async () => {
      result.current.deny('req-b', 'not allowed');
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:4300/api/v1/approvals/req-b/deny',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback: 'not allowed' }),
        credentials: 'include',
      }),
    );
  });

  it('optimistically removes from pending on successful approve', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: makeApprovalRequest('req-c') });
    });
    expect(result.current.pendingApprovals).toHaveLength(1);

    await act(async () => {
      result.current.approve('req-c');
    });

    expect(result.current.pendingApprovals).toHaveLength(0);
  });

  it('does not remove from pending when fetch fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateMessage({ type: 'approval_request', payload: makeApprovalRequest('req-d') });
    });
    expect(result.current.pendingApprovals).toHaveLength(1);

    await act(async () => {
      result.current.approve('req-d');
    });

    expect(result.current.pendingApprovals).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // Reconnection logic
  // -----------------------------------------------------------------------

  it('reconnects on abnormal close (code !== 1000)', () => {
    renderHook(() => useApprovals());
    const initialInstanceCount = MockWebSocket.instances.length;
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateClose(1006); // abnormal close
    });

    // Timer should be scheduled but no new instance yet
    expect(MockWebSocket.instances).toHaveLength(initialInstanceCount);

    // Advance timer by RECONNECT_DELAY_MS (2000ms)
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // A new WebSocket instance should have been created
    expect(MockWebSocket.instances.length).toBeGreaterThan(initialInstanceCount);
  });

  it('does not reconnect on normal close (code === 1000)', () => {
    renderHook(() => useApprovals());
    const ws = MockWebSocket.last;
    const initialInstanceCount = MockWebSocket.instances.length;

    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateClose(1000);
    });

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // No new instance should have been created
    expect(MockWebSocket.instances).toHaveLength(initialInstanceCount);
  });

  // -----------------------------------------------------------------------
  // Cleanup
  // -----------------------------------------------------------------------

  it('cleans up WebSocket on unmount (close called with code 1000)', () => {
    const { unmount } = renderHook(() => useApprovals());
    const ws = MockWebSocket.last;

    act(() => {
      ws.simulateOpen();
    });

    unmount();

    expect(ws.close).toHaveBeenCalledWith(1000, 'Component unmounted');
  });
});
