import { describe, it, expect, expectTypeOf } from "vitest";
import type {
  Agent,
  AgentRole,
  AgentStatus,
  SynergyBonus,
  PermissionMatrix,
  PermissionLevel,
  ActionCategory,
  ApprovalRequest,
  ApprovalResponse,
  GamepadInput,
  Department,
  OfficeState,
  TacticianPosition,
  Player,
  ChatMessage,
  ReviewStation,
  ComputeTokenBucket,
  SubscriptionTier,
  TierCapabilities,
  SubscriptionCapabilities,
} from "../index";

describe("AgentRole type", () => {
  it("accepts all valid role values", () => {
    const roles: AgentRole[] = [
      "planner",
      "coder",
      "reviewer",
      "researcher",
      "crm",
      "support",
    ];
    expect(roles).toHaveLength(6);
    roles.forEach((role) => {
      expect(typeof role).toBe("string");
    });
  });

  it("can be used as a discriminator in an Agent object", () => {
    const agent: Agent = {
      id: "agent-001",
      name: "CodeBot",
      role: "coder",
      status: "idle",
      level: 3,
      departmentId: "dept-eng",
      currentTaskId: null,
      synergyBonuses: [],
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
    };
    expect(agent.role).toBe("coder");
    expect(agent.departmentId).toBe("dept-eng");
  });
});

describe("AgentStatus type", () => {
  it("accepts all valid status values", () => {
    const statuses: AgentStatus[] = [
      "idle",
      "working",
      "waiting_approval",
      "paused",
      "error",
    ];
    expect(statuses).toHaveLength(5);
  });
});

describe("SynergyBonus type", () => {
  it("can be constructed with required fields", () => {
    const bonus: SynergyBonus = {
      name: "Pair Programming",
      description: "Two coders working together get a speed boost",
      multiplier: 1.5,
      requiredRoles: ["coder", "reviewer"],
    };
    expect(bonus.multiplier).toBe(1.5);
    expect(bonus.requiredRoles).toContain("coder");
    expect(bonus.requiredRoles).toContain("reviewer");
  });

  it("enforces requiredRoles as AgentRole array", () => {
    const bonus: SynergyBonus = {
      name: "Full Stack",
      description: "Cross-functional team synergy",
      multiplier: 2.0,
      requiredRoles: ["planner", "coder", "reviewer"],
    };
    expect(bonus.requiredRoles).toHaveLength(3);
  });
});

describe("Agent type", () => {
  it("can construct an agent with null department and task", () => {
    const agent: Agent = {
      id: "a-1",
      name: "Unassigned Agent",
      role: "researcher",
      status: "idle",
      level: 1,
      departmentId: null,
      currentTaskId: null,
      synergyBonuses: [],
      createdAt: "2026-03-01T00:00:00Z",
      updatedAt: "2026-03-01T00:00:00Z",
    };
    expect(agent.departmentId).toBeNull();
    expect(agent.currentTaskId).toBeNull();
  });

  it("can construct an agent with synergy bonuses", () => {
    const agent: Agent = {
      id: "a-2",
      name: "Senior Coder",
      role: "coder",
      status: "working",
      level: 5,
      departmentId: "dept-1",
      currentTaskId: "task-42",
      synergyBonuses: [
        {
          name: "Code Review Loop",
          description: "Coder + Reviewer synergy",
          multiplier: 1.3,
          requiredRoles: ["coder", "reviewer"],
        },
      ],
      createdAt: "2026-01-15T00:00:00Z",
      updatedAt: "2026-03-06T12:00:00Z",
    };
    expect(agent.synergyBonuses).toHaveLength(1);
    expect(agent.synergyBonuses[0].multiplier).toBe(1.3);
  });
});

describe("PermissionMatrix type", () => {
  it("can be constructed with all action categories", () => {
    const matrix: PermissionMatrix = {
      file_read: "allow",
      file_write: "ask",
      bash_execute: "deny",
      git_commit: "ask",
      git_push: "deny",
      email_send: "ask",
      crm_update: "allow",
      deploy: "deny",
      api_call: "allow",
    };
    expect(matrix.file_read).toBe("allow");
    expect(matrix.bash_execute).toBe("deny");
    expect(matrix.deploy).toBe("deny");
  });

  it("maps every ActionCategory to a PermissionLevel", () => {
    const categories: ActionCategory[] = [
      "file_read",
      "file_write",
      "bash_execute",
      "git_commit",
      "git_push",
      "email_send",
      "crm_update",
      "deploy",
      "api_call",
    ];
    const matrix: PermissionMatrix = {} as PermissionMatrix;
    for (const cat of categories) {
      matrix[cat] = "allow";
    }
    expect(Object.keys(matrix)).toHaveLength(9);
    Object.values(matrix).forEach((level) => {
      expect(["allow", "ask", "deny"]).toContain(level);
    });
  });
});

describe("ApprovalRequest type", () => {
  it("can be constructed with all required fields", () => {
    const request: ApprovalRequest = {
      id: "req-001",
      agentId: "agent-01",
      agentName: "CodeBot",
      actionCategory: "git_push",
      actionType: "push_to_main",
      payload: { branch: "main", commitHash: "abc123" },
      reasoning: "Feature branch is ready for merge",
      urgency: "high",
      createdAt: "2026-03-06T10:00:00Z",
    };
    expect(request.urgency).toBe("high");
    expect(request.actionCategory).toBe("git_push");
    expect(request.diff).toBeUndefined();
  });

  it("can include an optional diff field", () => {
    const request: ApprovalRequest = {
      id: "req-002",
      agentId: "agent-02",
      agentName: "ReviewBot",
      actionCategory: "file_write",
      actionType: "modify_config",
      payload: { file: "config.json" },
      diff: "- old_value\n+ new_value",
      reasoning: "Config update needed for new feature",
      urgency: "medium",
      createdAt: "2026-03-06T11:00:00Z",
    };
    expect(request.diff).toBeDefined();
    expect(request.diff).toContain("new_value");
  });
});

describe("ApprovalResponse type", () => {
  it("can represent an approved response", () => {
    const response: ApprovalResponse = {
      requestId: "req-001",
      result: "approved",
      respondedAt: "2026-03-06T10:05:00Z",
    };
    expect(response.result).toBe("approved");
    expect(response.feedback).toBeUndefined();
  });

  it("can represent a denied response with feedback", () => {
    const response: ApprovalResponse = {
      requestId: "req-001",
      result: "denied",
      feedback: "Needs more testing before push",
      respondedAt: "2026-03-06T10:05:00Z",
    };
    expect(response.result).toBe("denied");
    expect(response.feedback).toBe("Needs more testing before push");
  });
});

describe("GamepadInput type", () => {
  it("has correct shape with stick axes and buttons", () => {
    const input: GamepadInput = {
      leftStickX: 0.0,
      leftStickY: -1.0,
      rightStickX: 0.5,
      rightStickY: 0.5,
      buttonA: true,
      buttonB: false,
      buttonX: false,
      buttonY: true,
    };
    expect(typeof input.leftStickX).toBe("number");
    expect(typeof input.leftStickY).toBe("number");
    expect(typeof input.rightStickX).toBe("number");
    expect(typeof input.rightStickY).toBe("number");
    expect(typeof input.buttonA).toBe("boolean");
    expect(typeof input.buttonB).toBe("boolean");
    expect(typeof input.buttonX).toBe("boolean");
    expect(typeof input.buttonY).toBe("boolean");
  });

  it("accepts neutral gamepad state", () => {
    const neutral: GamepadInput = {
      leftStickX: 0,
      leftStickY: 0,
      rightStickX: 0,
      rightStickY: 0,
      buttonA: false,
      buttonB: false,
      buttonX: false,
      buttonY: false,
    };
    const allAxesZero =
      neutral.leftStickX === 0 &&
      neutral.leftStickY === 0 &&
      neutral.rightStickX === 0 &&
      neutral.rightStickY === 0;
    expect(allAxesZero).toBe(true);

    const allButtonsOff =
      !neutral.buttonA &&
      !neutral.buttonB &&
      !neutral.buttonX &&
      !neutral.buttonY;
    expect(allButtonsOff).toBe(true);
  });
});

describe("Department type", () => {
  it("can construct a department with agents", () => {
    const dept: Department = {
      id: "dept-eng",
      name: "Engineering",
      slug: "engineering",
      description: "Software development department",
      agents: [],
      maxAgents: 6,
      position: { x: 100, y: 200 },
    };
    expect(dept.agents).toEqual([]);
    expect(dept.position.x).toBe(100);
    expect(dept.maxAgents).toBe(6);
  });
});

describe("TacticianPosition type", () => {
  it("accepts all valid direction values", () => {
    const directions: TacticianPosition["direction"][] = [
      "up",
      "down",
      "left",
      "right",
    ];
    directions.forEach((dir) => {
      const pos: TacticianPosition = { x: 400, y: 300, direction: dir };
      expect(pos.direction).toBe(dir);
    });
  });
});

describe("OfficeState type", () => {
  it("can construct a complete office state", () => {
    const state: OfficeState = {
      departments: [],
      reviewStations: [],
      players: [
        { sessionId: "s1", name: "Alice", x: 400, y: 300, direction: "down" },
      ],
      localSessionId: "s1",
      activeAgentCount: 0,
      pendingApprovalCount: 0,
      chatMessages: [],
    };
    expect(state.departments).toEqual([]);
    expect(state.players).toHaveLength(1);
    expect(state.players[0].name).toBe("Alice");
    expect(state.activeAgentCount).toBe(0);
  });
});

describe("Player type", () => {
  it("can construct a player", () => {
    const player: Player = {
      sessionId: "abc",
      name: "Test",
      x: 100,
      y: 200,
      direction: "right",
    };
    expect(player.sessionId).toBe("abc");
  });
});

describe("ChatMessage type", () => {
  it("can construct a chat message", () => {
    const msg: ChatMessage = {
      id: "msg-1",
      senderSessionId: "s1",
      senderName: "Alice",
      content: "Hello",
      timestamp: Date.now(),
      isSystem: false,
    };
    expect(msg.content).toBe("Hello");
    expect(msg.isSystem).toBe(false);
  });

  it("can construct a system message", () => {
    const msg: ChatMessage = {
      id: "msg-2",
      senderSessionId: "",
      senderName: "System",
      content: "Alice joined",
      timestamp: Date.now(),
      isSystem: true,
    };
    expect(msg.isSystem).toBe(true);
  });
});

describe("Billing types", () => {
  it("can construct a ComputeTokenBucket", () => {
    const bucket: ComputeTokenBucket = {
      dailyLimit: 100000,
      used: 25000,
      remaining: 75000,
      resetAt: "2026-03-07T00:00:00Z",
    };
    expect(bucket.used + bucket.remaining).toBe(bucket.dailyLimit);
  });

  it("accepts all SubscriptionTier values", () => {
    const tiers: SubscriptionTier[] = [
      "starter",
      "professional",
      "enterprise",
    ];
    expect(tiers).toHaveLength(3);
  });

  it("can construct TierCapabilities", () => {
    const cap: TierCapabilities = {
      tier: "professional",
      maxAgents: 20,
      maxDepartments: 5,
      dailyComputeTokens: 500000,
      maxConcurrentTasks: 10,
      features: ["advanced_analytics", "custom_roles", "api_access"],
    };
    expect(cap.features).toContain("api_access");
    expect(cap.maxAgents).toBe(20);
  });

  it("can construct SubscriptionCapabilities", () => {
    const sub: SubscriptionCapabilities = {
      tier: "enterprise",
      capabilities: {
        tier: "enterprise",
        maxAgents: 100,
        maxDepartments: 20,
        dailyComputeTokens: 5000000,
        maxConcurrentTasks: 50,
        features: ["everything", "priority_support", "sla"],
      },
      computeTokens: {
        dailyLimit: 5000000,
        used: 0,
        remaining: 5000000,
        resetAt: "2026-03-07T00:00:00Z",
      },
      isActive: true,
    };
    expect(sub.isActive).toBe(true);
    expect(sub.tier).toBe(sub.capabilities.tier);
  });
});
