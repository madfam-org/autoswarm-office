import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { handleInteraction, handleApproval } from "../handlers/interaction";

// ---------------------------------------------------------------------------
// Helpers — plain objects cast with `as any` to avoid real Colyseus schemas
// ---------------------------------------------------------------------------

function makeAgent(overrides: {
  id: string;
  name: string;
  role: string;
  status?: string;
  level?: number;
  x?: number;
  y?: number;
}) {
  return {
    id: overrides.id,
    name: overrides.name,
    role: overrides.role,
    status: overrides.status ?? "idle",
    level: overrides.level ?? 1,
    x: overrides.x ?? 0,
    y: overrides.y ?? 0,
  } as any;
}

function makeDepartment(id: string, agents: any[]) {
  return { id, name: id, slug: id, maxAgents: 4, x: 0, y: 0, agents } as any;
}

function makeState(departments: Map<string, any>, pendingApprovalCount = 0) {
  return { departments, pendingApprovalCount } as any;
}

function makeClient(sessionId = "session-1") {
  return { sessionId, send: vi.fn() } as any;
}

/**
 * Build a state containing a single department with one agent.
 * Used by most handleApproval tests.
 */
function makeStateWithAgent(agentOverrides?: Record<string, unknown>) {
  const agent = makeAgent({
    id: "agent-1",
    name: "TestBot",
    role: "coder",
    status: "waiting_approval",
    ...agentOverrides,
  });
  const dept = makeDepartment("engineering", [agent]);
  const departments = new Map([["engineering", dept]]);
  return { state: makeState(departments, 1), agent };
}

// ---------------------------------------------------------------------------
// handleInteraction
// ---------------------------------------------------------------------------
describe("handleInteraction", () => {
  it("sends error when agentId is missing (empty string)", () => {
    const client = makeClient();
    const state = makeState(new Map());

    handleInteraction(state, client, { agentId: "" } as any);

    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_interaction",
      message: "agentId is required",
    });
  });

  it("sends error when agent not found in any department", () => {
    const client = makeClient();
    const dept = makeDepartment("engineering", [
      makeAgent({ id: "agent-1", name: "Bot", role: "coder" }),
    ]);
    const state = makeState(new Map([["engineering", dept]]));

    handleInteraction(state, client, { agentId: "nonexistent" } as any);

    expect(client.send).toHaveBeenCalledWith("error", {
      type: "agent_not_found",
      message: "Agent nonexistent not found in any department",
    });
  });

  it("sends show_approval_modal when agent status is waiting_approval", () => {
    const client = makeClient();
    const agent = makeAgent({
      id: "agent-1",
      name: "ApprovalBot",
      role: "reviewer",
      status: "waiting_approval",
      level: 3,
    });
    const dept = makeDepartment("qa", [agent]);
    const state = makeState(new Map([["qa", dept]]));

    handleInteraction(state, client, { agentId: "agent-1" } as any);

    expect(client.send).toHaveBeenCalledWith("show_approval_modal", {
      agentId: "agent-1",
      agentName: "ApprovalBot",
      agentRole: "reviewer",
      level: 3,
    });
  });

  it("sends agent_info for normal agent (idle status)", () => {
    const client = makeClient();
    const agent = makeAgent({
      id: "agent-2",
      name: "IdleBot",
      role: "planner",
      status: "idle",
      level: 2,
      x: 100,
      y: 200,
    });
    const dept = makeDepartment("ops", [agent]);
    const state = makeState(new Map([["ops", dept]]));

    handleInteraction(state, client, { agentId: "agent-2" } as any);

    expect(client.send).toHaveBeenCalledWith("agent_info", {
      id: "agent-2",
      name: "IdleBot",
      role: "planner",
      status: "idle",
      level: 2,
      x: 100,
      y: 200,
    });
  });

  it("sends agent_info for working agent", () => {
    const client = makeClient();
    const agent = makeAgent({
      id: "agent-3",
      name: "BusyBot",
      role: "coder",
      status: "working",
      level: 5,
      x: 300,
      y: 400,
    });
    const dept = makeDepartment("dev", [agent]);
    const state = makeState(new Map([["dev", dept]]));

    handleInteraction(state, client, { agentId: "agent-3" } as any);

    expect(client.send).toHaveBeenCalledWith("agent_info", {
      id: "agent-3",
      name: "BusyBot",
      role: "coder",
      status: "working",
      level: 5,
      x: 300,
      y: 400,
    });
  });

  it("finds agent across multiple departments", () => {
    const client = makeClient();
    const agent1 = makeAgent({ id: "a1", name: "Bot1", role: "coder" });
    const agent2 = makeAgent({
      id: "a2",
      name: "Bot2",
      role: "researcher",
      level: 4,
      x: 50,
      y: 75,
    });
    const dept1 = makeDepartment("engineering", [agent1]);
    const dept2 = makeDepartment("research", [agent2]);
    const state = makeState(
      new Map([
        ["engineering", dept1],
        ["research", dept2],
      ])
    );

    handleInteraction(state, client, { agentId: "a2" } as any);

    expect(client.send).toHaveBeenCalledWith("agent_info", {
      id: "a2",
      name: "Bot2",
      role: "researcher",
      status: "idle",
      level: 4,
      x: 50,
      y: 75,
    });
  });
});

// ---------------------------------------------------------------------------
// handleApproval
// ---------------------------------------------------------------------------
describe("handleApproval", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ agentId: "agent-1" }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends error when requestId is missing", async () => {
    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_approval",
      message: "requestId and result are required",
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("sends error when result is missing", async () => {
    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_approval",
      message: "requestId and result are required",
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("calls fetch with correct URL and body", async () => {
    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-42",
      result: "approved",
      feedback: "Looks good",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("http://localhost:4300/api/v1/approvals/req-42/approve");
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });

    const body = JSON.parse(options.body);
    expect(body.feedback).toBe("Looks good");
  });

  it("updates agent status to 'working' on approved", async () => {
    const client = makeClient();
    const { state, agent } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(agent.status).toBe("working");
  });

  it("updates agent status to 'idle' on denied", async () => {
    const client = makeClient();
    const { state, agent } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "denied",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(agent.status).toBe("idle");
  });

  it("decrements pendingApprovalCount and does not go below 0", async () => {
    const client = makeClient();
    const { state } = makeStateWithAgent();
    state.pendingApprovalCount = 1;

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(state.pendingApprovalCount).toBe(0);

    // Call again -- should stay at 0, not go negative
    await handleApproval(state, client, {
      requestId: "req-2",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(state.pendingApprovalCount).toBe(0);
  });

  it("sends approval_error on non-ok fetch response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => "Internal Server Error",
    });

    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(client.send).toHaveBeenCalledWith("approval_error", {
      requestId: "req-1",
      message: "Nexus API error: 500",
    });
  });

  it("sends approval_error on network error (fetch throws)", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network failure"));

    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(client.send).toHaveBeenCalledWith("approval_error", {
      requestId: "req-1",
      message: "Failed to communicate with nexus-api",
    });
  });

  it("sends approval_confirmed on success", async () => {
    const client = makeClient();
    const { state } = makeStateWithAgent();

    await handleApproval(state, client, {
      requestId: "req-1",
      result: "approved",
      nexusApiUrl: "http://localhost:4300",
    } as any);

    expect(client.send).toHaveBeenCalledWith("approval_confirmed", {
      requestId: "req-1",
      result: "approved",
    });
  });
});
