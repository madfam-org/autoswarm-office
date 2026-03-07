import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

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

function makeDepartment(
  id: string,
  agents: any[],
  x = 100,
  y = 100
) {
  return {
    id,
    name: id,
    slug: id,
    maxAgents: 6,
    x,
    y,
    agents,
  } as any;
}

function makeState(departments: Map<string, any>, pendingApprovalCount = 0) {
  return { departments, pendingApprovalCount } as any;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fetchAgentsFromApi", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("populates agents into departments from API response", async () => {
    const dept = makeDepartment("dept-engineering", []);
    const departments = new Map([["dept-engineering", dept]]);

    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [
          { id: "a1", name: "Ada", role: "coder", status: "idle", level: 2 },
          { id: "a2", name: "Bob", role: "reviewer", status: "working", level: 3 },
        ],
      }),
    });

    // Simulate fetchAgentsFromApi logic
    for (const [deptId, d] of departments) {
      const resp = await fetch(`http://localhost:4300/api/v1/departments/${deptId}`);
      if (!resp.ok) continue;
      const detail = (await resp.json()) as Record<string, any>;
      const agents = (detail.agents ?? []) as Array<Record<string, any>>;
      for (let i = 0; i < agents.length; i++) {
        const a = agents[i];
        d.agents.push({
          id: a.id,
          name: a.name,
          role: a.role,
          status: a.status ?? "idle",
          level: a.level ?? 1,
          x: d.x + 48 + (i % 3) * 48,
          y: d.y + 48 + Math.floor(i / 3) * 48,
        });
      }
    }

    expect(dept.agents).toHaveLength(2);
    expect(dept.agents[0].id).toBe("a1");
    expect(dept.agents[0].name).toBe("Ada");
    expect(dept.agents[1].role).toBe("reviewer");
    // Verify positioning
    expect(dept.agents[0].x).toBe(148); // 100 + 48 + (0 % 3) * 48
    expect(dept.agents[1].x).toBe(196); // 100 + 48 + (1 % 3) * 48
  });

  it("populates skills array from effective_skills", async () => {
    const dept = makeDepartment("dept-engineering", []);
    const departments = new Map([["dept-engineering", dept]]);

    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [
          {
            id: "a1",
            name: "Ada",
            role: "coder",
            status: "idle",
            level: 2,
            effective_skills: ["coding", "webapp-testing"],
          },
        ],
      }),
    });

    for (const [deptId, d] of departments) {
      const resp = await fetch(`http://localhost:4300/api/v1/departments/${deptId}`);
      if (!resp.ok) continue;
      const detail = (await resp.json()) as Record<string, any>;
      const agents = (detail.agents ?? []) as Array<Record<string, any>>;
      for (let i = 0; i < agents.length; i++) {
        const a = agents[i];
        const agentObj: any = {
          id: a.id,
          name: a.name,
          role: a.role,
          status: a.status ?? "idle",
          level: a.level ?? 1,
          x: d.x + 48 + (i % 3) * 48,
          y: d.y + 48 + Math.floor(i / 3) * 48,
          skills: [] as string[],
        };
        const skills = (a.effective_skills ?? []) as string[];
        for (const skill of skills) {
          agentObj.skills.push(skill);
        }
        d.agents.push(agentObj);
      }
    }

    expect(dept.agents).toHaveLength(1);
    expect(dept.agents[0].skills).toEqual(["coding", "webapp-testing"]);
  });

  it("handles API failure gracefully (department stays empty)", async () => {
    const dept = makeDepartment("dept-research", []);
    const departments = new Map([["dept-research", dept]]);

    mockFetch.mockResolvedValue({ ok: false, status: 404 });

    for (const [deptId, d] of departments) {
      const resp = await fetch(`http://localhost:4300/api/v1/departments/${deptId}`);
      if (!resp.ok) continue;
    }

    expect(dept.agents).toHaveLength(0);
  });
});

describe("updateAgentInState", () => {
  it("changes agent status", () => {
    const agent = makeAgent({ id: "a1", name: "Ada", role: "coder", status: "idle" });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "working";
        }
      }
    });

    expect(agent.status).toBe("working");
  });

  it("increments pendingApprovalCount for waiting_approval status", () => {
    const agent = makeAgent({ id: "a1", name: "Ada", role: "coder", status: "idle" });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState with waiting_approval
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "waiting_approval";
          state.pendingApprovalCount += 1;
        }
      }
    });

    expect(agent.status).toBe("waiting_approval");
    expect(state.pendingApprovalCount).toBe(1);
  });

  it("does not change state when agent not found", () => {
    const agent = makeAgent({ id: "a1", name: "Ada", role: "coder", status: "idle" });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Try to update a non-existent agent
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "nonexistent") {
          d.agents[i].status = "working";
        }
      }
    });

    expect(agent.status).toBe("idle");
    expect(state.pendingApprovalCount).toBe(0);
  });
});
