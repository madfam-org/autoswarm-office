import { Room, Client } from "@colyseus/core";
import {
  OfficeStateSchema,
  DepartmentSchema,
  AgentSchema,
  TacticianSchema,
} from "../schema/OfficeState";
import { handleMovement } from "../handlers/movement";
import { handleInteraction, handleApproval } from "../handlers/interaction";

interface MoveMessage {
  x: number;
  y: number;
}

interface InteractMessage {
  agentId: string;
}

interface ApproveMessage {
  requestId: string;
  result: "approved" | "denied";
  feedback?: string;
}

interface RoomOptions {
  nexusApiUrl?: string;
}

const DEFAULT_DEPARTMENTS: Array<{
  id: string;
  name: string;
  slug: string;
  maxAgents: number;
  x: number;
  y: number;
}> = [
  {
    id: "dept-engineering",
    name: "Engineering",
    slug: "engineering",
    maxAgents: 6,
    x: 100,
    y: 100,
  },
  {
    id: "dept-research",
    name: "Research",
    slug: "research",
    maxAgents: 4,
    x: 600,
    y: 100,
  },
  {
    id: "dept-crm",
    name: "CRM",
    slug: "crm",
    maxAgents: 4,
    x: 100,
    y: 400,
  },
  {
    id: "dept-support",
    name: "Support",
    slug: "support",
    maxAgents: 4,
    x: 600,
    y: 400,
  },
];

export class OfficeRoom extends Room<OfficeStateSchema> {
  private nexusApiUrl: string = "http://localhost:4300";

  onCreate(options: RoomOptions): void {
    console.log("[OfficeRoom] Room created");

    this.setState(new OfficeStateSchema());

    this.nexusApiUrl =
      options.nexusApiUrl ??
      process.env.NEXUS_API_URL ??
      this.nexusApiUrl;

    for (const dept of DEFAULT_DEPARTMENTS) {
      const department = new DepartmentSchema();
      department.id = dept.id;
      department.name = dept.name;
      department.slug = dept.slug;
      department.maxAgents = dept.maxAgents;
      department.x = dept.x;
      department.y = dept.y;
      this.state.departments.set(dept.id, department);
    }

    const tactician = new TacticianSchema();
    tactician.x = 400;
    tactician.y = 300;
    tactician.direction = "down";
    this.state.tactician = tactician;

    this.onMessage("move", (client: Client, message: MoveMessage) => {
      handleMovement(this.state, client, message);
    });

    this.onMessage("interact", (client: Client, message: InteractMessage) => {
      handleInteraction(this.state, client, message);
    });

    this.onMessage("approve", (client: Client, message: ApproveMessage) => {
      handleApproval(this.state, client, {
        ...message,
        nexusApiUrl: this.nexusApiUrl,
      });
    });

    this.onMessage("deny", (client: Client, message: ApproveMessage) => {
      handleApproval(this.state, client, {
        ...message,
        result: "denied",
        nexusApiUrl: this.nexusApiUrl,
      });
    });

    console.log(
      `[OfficeRoom] Initialized with ${DEFAULT_DEPARTMENTS.length} departments`
    );

    // Fire-and-forget: populate agents from nexus-api database.
    this.fetchAgentsFromApi().catch((err) =>
      console.error("[OfficeRoom] Failed to fetch agents:", err)
    );

    // Fire-and-forget: subscribe to real-time agent status updates via Redis.
    this.subscribeToAgentUpdates().catch((err) =>
      console.error("[OfficeRoom] Failed to subscribe to agent updates:", err)
    );
  }

  onJoin(client: Client): void {
    console.log(`[OfficeRoom] Client joined: ${client.sessionId}`);
    this.broadcast("player_joined", { sessionId: client.sessionId });
  }

  onLeave(client: Client, consented: boolean): void {
    console.log(
      `[OfficeRoom] Client left: ${client.sessionId} (consented: ${consented})`
    );
    this.broadcast("player_left", { sessionId: client.sessionId });
  }

  onDispose(): void {
    console.log("[OfficeRoom] Room disposed");
    if (this.redisSubscriber) {
      this.redisSubscriber.quit().catch(() => {});
    }
  }

  // -- Agent sync from database -----------------------------------------------

  private redisSubscriber: import("redis").RedisClientType | null = null;

  private async fetchAgentsFromApi(): Promise<void> {
    for (const [deptId, dept] of this.state.departments) {
      try {
        const resp = await fetch(
          `${this.nexusApiUrl}/api/v1/departments/${deptId}`
        );
        if (!resp.ok) continue;
        const detail = (await resp.json()) as Record<string, any>;
        const agents = (detail.agents ?? []) as Array<Record<string, any>>;
        for (let i = 0; i < agents.length; i++) {
          const a = agents[i];
          const agent = new AgentSchema();
          agent.id = a.id;
          agent.name = a.name;
          agent.role = a.role;
          agent.status = a.status ?? "idle";
          agent.level = a.level ?? 1;
          agent.x = dept.x + 48 + (i % 3) * 48;
          agent.y = dept.y + 48 + Math.floor(i / 3) * 48;
          const skills = (a.effective_skills ?? []) as string[];
          for (const skill of skills) {
            agent.skills.push(skill);
          }
          dept.agents.push(agent);
        }
        console.log(
          `[OfficeRoom] Loaded ${agents.length} agents into ${deptId}`
        );
      } catch (err) {
        console.error(
          `[OfficeRoom] Failed to fetch agents for ${deptId}:`,
          err
        );
      }
    }
  }

  private async subscribeToAgentUpdates(): Promise<void> {
    const { createClient } = await import("redis");
    const redisUrl = process.env.REDIS_URL ?? "redis://localhost:6379";
    this.redisSubscriber = createClient({ url: redisUrl });
    await this.redisSubscriber.connect();
    await this.redisSubscriber.subscribe(
      "autoswarm:agent-status",
      (message: string) => {
        try {
          const update = JSON.parse(message) as {
            agent_id: string;
            status: string;
          };
          this.updateAgentInState(update.agent_id, update.status);
        } catch (err) {
          console.error("[OfficeRoom] Bad agent-status message:", err);
        }
      }
    );
    console.log("[OfficeRoom] Subscribed to autoswarm:agent-status channel");
  }

  private updateAgentInState(agentId: string, status: string): void {
    this.state.departments.forEach((dept) => {
      for (let i = 0; i < dept.agents.length; i++) {
        const agent = dept.agents[i];
        if (agent && agent.id === agentId) {
          agent.status = status;
          if (status === "waiting_approval") {
            this.state.pendingApprovalCount += 1;
          }
          return;
        }
      }
    });
  }
}
