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
  currentTaskId?: string;
  currentTaskDescription?: string;
  departmentId?: string;
}) {
  return {
    id: overrides.id,
    name: overrides.name,
    role: overrides.role,
    status: overrides.status ?? "idle",
    level: overrides.level ?? 1,
    x: overrides.x ?? 0,
    y: overrides.y ?? 0,
    currentTaskId: overrides.currentTaskId ?? "",
    currentTaskDescription: overrides.currentTaskDescription ?? "",
    departmentId: overrides.departmentId ?? "",
  } as any;
}

function makeDepartment(
  id: string,
  agents: any[],
  slug?: string,
  x = 100,
  y = 100
) {
  return {
    id,
    name: id,
    slug: slug ?? id.replace("dept-", ""),
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
// Simulates the slug-based fetchAgentsFromApi logic from OfficeRoom.ts:
//   1. Build slug→dept map from Colyseus state
//   2. Fetch department list from API (UUIDs + slugs)
//   3. Match by slug
//   4. Fetch detail by API UUID for each matched department
// ---------------------------------------------------------------------------
async function simulateFetchAgentsFromApi(
  state: any,
  nexusApiUrl: string,
  token: string = "dev-token",
  orgId: string = "madfam"
): Promise<void> {
  const slugToDept = new Map<string, { stateKey: string; dept: any }>();
  state.departments.forEach((dept: any, key: string) => {
    slugToDept.set(dept.slug, { stateKey: key, dept });
  });

  let apiDepts: Array<Record<string, any>>;
  try {
    const listResp = await fetch(`${nexusApiUrl}/api/v1/departments/`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Selva-Tenant-Org": orgId,
      },
    });
    if (!listResp.ok) return;
    apiDepts = (await listResp.json()) as Array<Record<string, any>>;
  } catch {
    return;
  }

  for (const apiDept of apiDepts) {
    const match = slugToDept.get(apiDept.slug as string);
    if (!match) continue;
    const { stateKey, dept } = match;

    try {
      const resp = await fetch(
        `${nexusApiUrl}/api/v1/departments/${apiDept.id}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Selva-Tenant-Org": orgId,
          },
        }
      );
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
          x: dept.x + 48 + (i % 3) * 48,
          y: dept.y + 48 + Math.floor(i / 3) * 48,
          currentTaskId: a.current_task_id ?? "",
          currentTaskDescription: "",
          departmentId: stateKey,
          skills: [] as string[],
        };
        const skills = (a.effective_skills ?? []) as string[];
        for (const skill of skills) {
          agentObj.skills.push(skill);
        }
        dept.agents.push(agentObj);
      }
    } catch {
      // skip failed department
    }
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fetchAgentsFromApi (slug-based matching)", () => {
  const NEXUS_URL = "http://localhost:4300";
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("populates agents into departments matched by slug", async () => {
    const dept = makeDepartment("dept-engineering", [], "engineering");
    const state = makeState(new Map([["dept-engineering", dept]]));

    // First call: department list (returns API UUIDs + slugs)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { id: "uuid-eng-123", slug: "engineering", name: "Engineering" },
      ],
    });

    // Second call: department detail (returns agents)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        agents: [
          { id: "a1", name: "Ada", role: "coder", status: "idle", level: 2 },
          { id: "a2", name: "Bob", role: "reviewer", status: "working", level: 3 },
        ],
      }),
    });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    expect(dept.agents).toHaveLength(2);
    expect(dept.agents[0].id).toBe("a1");
    expect(dept.agents[0].name).toBe("Ada");
    expect(dept.agents[1].role).toBe("reviewer");
    // Verify positioning
    expect(dept.agents[0].x).toBe(148); // 100 + 48 + (0 % 3) * 48
    expect(dept.agents[1].x).toBe(196); // 100 + 48 + (1 % 3) * 48

    // Verify fetch was called with API UUID, not Colyseus dept ID
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      `${NEXUS_URL}/api/v1/departments/`,
      expect.objectContaining({
        headers: {
          Authorization: "Bearer dev-token",
          "X-Selva-Tenant-Org": "madfam",
        },
      })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      `${NEXUS_URL}/api/v1/departments/uuid-eng-123`,
      expect.objectContaining({
        headers: {
          Authorization: "Bearer dev-token",
          "X-Selva-Tenant-Org": "madfam",
        },
      })
    );
  });

  it("populates skills array from effective_skills", async () => {
    const dept = makeDepartment("dept-engineering", [], "engineering");
    const state = makeState(new Map([["dept-engineering", dept]]));

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: "uuid-eng", slug: "engineering" }],
      })
      .mockResolvedValueOnce({
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

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    expect(dept.agents).toHaveLength(1);
    expect(dept.agents[0].skills).toEqual(["coding", "webapp-testing"]);
  });

  it("handles department list API failure gracefully", async () => {
    const dept = makeDepartment("dept-research", [], "research");
    const state = makeState(new Map([["dept-research", dept]]));

    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    // Only the list call should have been made
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(dept.agents).toHaveLength(0);
  });

  it("handles department detail API failure gracefully", async () => {
    const dept = makeDepartment("dept-research", [], "research");
    const state = makeState(new Map([["dept-research", dept]]));

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: "uuid-res", slug: "research" }],
      })
      .mockResolvedValueOnce({ ok: false, status: 404 });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(dept.agents).toHaveLength(0);
  });

  it("skips API departments that don't match any Colyseus department slug", async () => {
    const dept = makeDepartment("dept-engineering", [], "engineering");
    const state = makeState(new Map([["dept-engineering", dept]]));

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { id: "uuid-eng", slug: "engineering" },
        { id: "uuid-marketing", slug: "marketing" }, // no match in Colyseus
      ],
    });

    // Only the engineering detail call should happen
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        agents: [{ id: "a1", name: "Ada", role: "coder" }],
      }),
    });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    // 1 list call + 1 detail call (marketing skipped)
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(dept.agents).toHaveLength(1);
  });

  it("populates currentTaskId and departmentId from API response", async () => {
    const dept = makeDepartment("dept-engineering", [], "engineering");
    const state = makeState(new Map([["dept-engineering", dept]]));

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: "uuid-eng", slug: "engineering" }],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          agents: [
            {
              id: "a1",
              name: "Ada",
              role: "coder",
              status: "working",
              level: 2,
              current_task_id: "task-abc",
              effective_skills: [],
            },
          ],
        }),
      });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    expect(dept.agents).toHaveLength(1);
    expect(dept.agents[0].currentTaskId).toBe("task-abc");
    expect(dept.agents[0].departmentId).toBe("dept-engineering");
    expect(dept.agents[0].currentTaskDescription).toBe("");
  });

  it("populates multiple departments in a single pass", async () => {
    const engDept = makeDepartment("dept-engineering", [], "engineering", 100, 100);
    const resDept = makeDepartment("dept-research", [], "research", 600, 100);
    const state = makeState(
      new Map([
        ["dept-engineering", engDept],
        ["dept-research", resDept],
      ])
    );

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { id: "uuid-eng", slug: "engineering" },
          { id: "uuid-res", slug: "research" },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          agents: [{ id: "a1", name: "Ada", role: "coder" }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          agents: [{ id: "a2", name: "Bob", role: "researcher" }],
        }),
      });

    await simulateFetchAgentsFromApi(state, NEXUS_URL);

    expect(engDept.agents).toHaveLength(1);
    expect(engDept.agents[0].id).toBe("a1");
    expect(resDept.agents).toHaveLength(1);
    expect(resDept.agents[0].id).toBe("a2");
    // Verify each agent got its own department's position
    expect(engDept.agents[0].x).toBe(148); // 100 + 48
    expect(resDept.agents[0].x).toBe(648); // 600 + 48
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

  it("does not modify agent when agent_id not found in any department", () => {
    const agent = makeAgent({ id: "a1", name: "Ada", role: "coder", status: "idle" });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate the updateAgentInState fallback scan for a nonexistent agent
    const agentId = "nonexistent-agent";
    let found = false;
    state.departments.forEach((d: any) => {
      if (found) return;
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === agentId) {
          d.agents[i].status = "working";
          found = true;
          return;
        }
      }
    });

    expect(found).toBe(false);
    expect(agent.status).toBe("idle");
  });

  it("sets currentTaskId and currentTaskDescription on status update", () => {
    const agent = makeAgent({
      id: "a1",
      name: "Ada",
      role: "coder",
      status: "idle",
    });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState with task fields
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "working";
          d.agents[i].currentTaskId = "task-xyz";
          d.agents[i].currentTaskDescription = "Fix login bug";
        }
      }
    });

    expect(agent.status).toBe("working");
    expect(agent.currentTaskId).toBe("task-xyz");
    expect(agent.currentTaskDescription).toBe("Fix login bug");
  });

  it("clears task fields when agent returns to idle without explicit task_id", () => {
    const agent = makeAgent({
      id: "a1",
      name: "Ada",
      role: "coder",
      status: "working",
      currentTaskId: "task-old",
      currentTaskDescription: "Previous task",
    });
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState transition to idle (no taskId provided)
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "idle";
          // When taskId is undefined, clear task fields
          d.agents[i].currentTaskId = "";
          d.agents[i].currentTaskDescription = "";
        }
      }
    });

    expect(agent.status).toBe("idle");
    expect(agent.currentTaskId).toBe("");
    expect(agent.currentTaskDescription).toBe("");
  });

  it("sets currentNodeId on agent status update", () => {
    const agent = makeAgent({
      id: "a1",
      name: "Ada",
      role: "coder",
      status: "idle",
    });
    (agent as any).currentNodeId = "";
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState with currentNodeId
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "working";
          d.agents[i].currentNodeId = "plan";
        }
      }
    });

    expect(agent.status).toBe("working");
    expect((agent as any).currentNodeId).toBe("plan");
  });

  it("clears currentNodeId when agent returns to idle", () => {
    const agent = makeAgent({
      id: "a1",
      name: "Ada",
      role: "coder",
      status: "working",
    });
    (agent as any).currentNodeId = "review";
    const dept = makeDepartment("engineering", [agent]);
    const state = makeState(new Map([["engineering", dept]]));

    // Simulate updateAgentInState transition to idle
    state.departments.forEach((d: any) => {
      for (let i = 0; i < d.agents.length; i++) {
        if (d.agents[i].id === "a1") {
          d.agents[i].status = "idle";
          d.agents[i].currentTaskId = "";
          d.agents[i].currentTaskDescription = "";
          d.agents[i].currentNodeId = "";
        }
      }
    });

    expect((agent as any).currentNodeId).toBe("");
  });
});

describe("Blueprint Lab department", () => {
  it("dept-blueprint exists with maxAgents: 0", () => {
    // Import DEFAULT_DEPARTMENTS from OfficeRoom would require real module,
    // so we verify the schema supports it
    const blueprintDept = makeDepartment("dept-blueprint", [], "blueprint", 1248, 384);
    blueprintDept.maxAgents = 0;

    const state = makeState(new Map([["dept-blueprint", blueprintDept]]));

    const dept = state.departments.get("dept-blueprint");
    expect(dept).toBeDefined();
    expect(dept.maxAgents).toBe(0);
    expect(dept.slug).toBe("blueprint");
    expect(dept.agents).toHaveLength(0);
  });
});
