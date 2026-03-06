import { Room, Client } from "@colyseus/core";
import {
  OfficeStateSchema,
  DepartmentSchema,
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
  private nexusApiUrl: string = "http://localhost:4000";

  onCreate(options: RoomOptions): void {
    console.log("[OfficeRoom] Room created");

    this.setState(new OfficeStateSchema());

    if (options.nexusApiUrl) {
      this.nexusApiUrl = options.nexusApiUrl;
    }

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
  }
}
