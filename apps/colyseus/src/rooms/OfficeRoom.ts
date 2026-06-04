import { Room, Client } from "@colyseus/core";
import {
  OfficeStateSchema,
  DepartmentSchema,
  AgentSchema,
  TacticianSchema,
} from "../schema/OfficeState";
import { handleMovement } from "../handlers/movement";
import { handleInteraction, handleApproval } from "../handlers/interaction";
import { handleChat, addSystemMessage, type ChatAuthContext } from "../handlers/chat";
import { handleEmote } from "../handlers/emotes";
import { handleAvatar } from "../handlers/avatar";
import { handleStatus, handleMusicStatus, handleMeetingTitle } from "../handlers/status";
import {
  startProximityLoop,
  lockBubble,
  unlockBubble,
  removeFromLockedGroups,
  isInLockedBubble,
} from "../handlers/proximity";
import {
  generateLiveKitToken,
  isLiveKitEnabled,
  getLiveKitUrl,
} from "../handlers/livekit";
import {
  handleMegaphoneStart,
  handleMegaphoneStop,
  releaseMegaphone,
} from "../handlers/megaphone";
import {
  handleSpotlightStart,
  handleSpotlightStop,
  releaseSpotlight,
} from "../handlers/spotlight";
import { handleSignaling } from "../handlers/signaling";
import type { WebRTCSignalMessage } from "../handlers/signaling";
import { handleCompanion } from "../handlers/companion";
import { handleTeleport } from "../handlers/teleport";
import {
  handleWhiteboardDraw,
  handleWhiteboardClear,
} from "../handlers/whiteboard";
import type {
  DrawStrokeMessage,
  ClearWhiteboardMessage,
} from "../handlers/whiteboard";
import { WhiteboardSchema } from "../schema/Whiteboard";
import { MessageThrottler } from "../throttle";
import { verifyToken, type AuthResult } from "../auth";
import { DemoSimulator } from "../demo/DemoSimulator";
import { createLogger } from "@selva/config/logging";
import { getRedisClient, closeRedisClient } from "../redis-client";
import type { RedisClientType } from "redis";

const logger = createLogger({ service: "colyseus" }).child({ component: "OfficeRoom" });

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

interface ChatMessage {
  content: string;
}

interface EmoteMessage {
  type: string;
}

interface AvatarMessage {
  config: string;
}

interface StatusMessage {
  status: string;
}

// Client-supplied join payload. Renamed from `RoomOptions` to avoid collision
// with `@colyseus/core`'s `RoomOptions` (which is the room metadata type for
// declaring state/client types — see `Room<{ state: OfficeStateSchema }>` below).
interface OfficeJoinOptions {
  nexusApiUrl?: string;
  name?: string;
  token?: string;
  orgId?: string;
}

/** Message types that guests are blocked from sending. */
const GUEST_BLOCKED_MESSAGES = new Set([
  "approve", "deny", "megaphone_start", "spotlight_start",
]);

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
  {
    id: "dept-blueprint",
    name: "Blueprint Lab",
    slug: "blueprint",
    maxAgents: 0,
    x: 800,
    y: 260,
  },
];

// @colyseus/core 0.17.x: the Room generic is a metadata object declaring
// the room's state/client/metadata types (see RoomOptions in @colyseus/core).
// State is also assigned explicitly via `setState(new OfficeStateSchema())`
// in onCreate (kept below for explicit ordering with the seed-departments path).
export class OfficeRoom extends Room<{ state: OfficeStateSchema }> {

  private nexusApiUrl: string = process.env.NEXUS_API_URL ?? "http://localhost:4300";
  private stopProximityLoop: (() => void) | null = null;
  private agentIndex = new Map<string, { deptId: string; agentIndex: number }>();
  private redisSubscriber: RedisClientType | null = null;
  private throttler = new MessageThrottler();
  private demoSimulator: DemoSimulator | null = null;
  private roomOrgId: string | null = null;

  /**
   * Return the service-to-service auth token for nexus-api calls.
   * Falls back to "dev-token" only when DEV_AUTH_BYPASS is enabled.
   */
  private getServiceToken(): string {
    if (process.env.COLYSEUS_SERVICE_TOKEN) {
      return process.env.COLYSEUS_SERVICE_TOKEN;
    }
    if (process.env.DEV_AUTH_BYPASS === "true") {
      return "dev-token";
    }
    logger.warn("COLYSEUS_SERVICE_TOKEN not set and DEV_AUTH_BYPASS is not enabled — using empty token");
    return "";
  }

  /**
   * Build the auth context for fire-and-forget chat-persistence calls
   * to nexus-api. The org_id is taken from the joining client's verified
   * Janua claims (when available); the room-level fallback is "default".
   *
   * Returns undefined when no service token is available -- the chat
   * handler will then skip persistence rather than POST anonymously.
   */
  private getChatAuth(client?: Client): ChatAuthContext | undefined {
    const token = this.getServiceToken();
    if (!token) {
      return undefined;
    }
    let orgId = "default";
    if (client) {
      const auth = client.auth as AuthResult | undefined;
      if (auth?.orgId) {
        orgId = auth.orgId;
      }
    }
    return { serviceToken: token, orgId };
  }

  private getServiceTenantOrg(): string | null {
    return (
      this.roomOrgId ??
      process.env.COLYSEUS_TENANT_ORG_ID ??
      process.env.PLATFORM_ORG_ID ??
      null
    );
  }

  private getServiceAuthHeaders(): Record<string, string> | null {
    const token = this.getServiceToken();
    const orgId = this.getServiceTenantOrg();
    if (!token || !orgId) {
      return null;
    }
    return {
      Authorization: `Bearer ${token}`,
      "X-Selva-Tenant-Org": orgId,
    };
  }

  /**
   * Register a message handler that is subject to per-session throttling.
   * If the session exceeds the rate limit the handler is skipped and a
   * ``rate_limited`` message is sent back to the client instead.
   */
  private throttledMessage<T>(
    type: string,
    handler: (client: Client, message: T) => void,
  ): void {
    this.onMessage(type, (client: Client, message: T) => {
      if (!this.throttler.check(client.sessionId, type)) {
        client.send("rate_limited", { type });
        return;
      }
      handler(client, message);
    });
  }

  /**
   * Authenticate the client before allowing them to join.
   * Verifies the JWT from Janua. Returns auth data stored on `client.auth`.
   */
  async onAuth(_client: Client, options: OfficeJoinOptions): Promise<AuthResult> {
    return verifyToken(options.token, { name: options.name });
  }

  /** Check if a client is a guest and send a permission error if so. */
  private isGuestBlocked(client: Client, action: string): boolean {
    const auth = client.auth as AuthResult | undefined;
    if (auth?.isGuest) {
      client.send("error", {
        type: "permission_denied",
        message: `Guests cannot use ${action}`,
      });
      return true;
    }
    return false;
  }

  onCreate(options: OfficeJoinOptions): void {
    logger.info("Room created");

    this.setState(new OfficeStateSchema());

    this.nexusApiUrl =
      options.nexusApiUrl ??
      process.env.NEXUS_API_URL ??
      this.nexusApiUrl;
    this.roomOrgId =
      process.env.COLYSEUS_TENANT_ORG_ID ??
      process.env.PLATFORM_ORG_ID ??
      this.roomOrgId;

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

    this.onMessage("move", (client: Client, message: MoveMessage) => {
      handleMovement(this.state, client, message);
    });

    this.throttledMessage("interact", (client: Client, message: InteractMessage) => {
      handleInteraction(this.state, client, message);
    });

    this.throttledMessage("approve", (client: Client, message: ApproveMessage) => {
      if (this.isGuestBlocked(client, "approve")) return;
      // In demo mode, resolve locally instead of calling the real API
      if (this.demoSimulator && message.requestId?.startsWith("demo-agent-")) {
        this.demoSimulator.resolveApproval(message.requestId, "approved");
        return;
      }
      handleApproval(this.state, client, {
        ...message,
        nexusApiUrl: this.nexusApiUrl,
      });
    });

    this.throttledMessage("deny", (client: Client, message: ApproveMessage) => {
      if (this.isGuestBlocked(client, "deny")) return;
      // In demo mode, resolve locally instead of calling the real API
      if (this.demoSimulator && message.requestId?.startsWith("demo-agent-")) {
        this.demoSimulator.resolveApproval(message.requestId, "denied");
        return;
      }
      handleApproval(this.state, client, {
        ...message,
        result: "denied",
        nexusApiUrl: this.nexusApiUrl,
      });
    });

    this.throttledMessage("chat", (client: Client, message: ChatMessage) => {
      handleChat(this.state, client, message, "office", this.getChatAuth(client));
    });

    this.throttledMessage("emote", (client: Client, message: EmoteMessage) => {
      handleEmote(this.state, client, message, (type, payload) =>
        this.broadcast(type, payload)
      );
    });

    this.throttledMessage("avatar", (client: Client, message: AvatarMessage) => {
      handleAvatar(this.state, client, message);
    });

    // "webrtc_signal" is exempt from throttling (high-frequency by design).
    this.onMessage(
      "webrtc_signal",
      (client: Client, message: WebRTCSignalMessage) => {
        handleSignaling(client, message, () => this.clients);
      }
    );

    this.throttledMessage("status", (client: Client, message: StatusMessage) => {
      handleStatus(this.state, client, message);
    });

    this.throttledMessage("music_status", (client: Client, message: { status: string }) => {
      handleMusicStatus(this.state, client, message);
    });

    this.throttledMessage("meeting_title", (client: Client, message: { title: string }) => {
      handleMeetingTitle(this.state, client, message);
    });

    this.throttledMessage("lock_bubble", (client: Client) => {
      const locked = lockBubble(client.sessionId, this.state);
      client.send("bubble_lock_status", { locked });
      if (locked) {
        logger.info({ sessionId: client.sessionId }, "Bubble locked");
      }
    });

    this.throttledMessage("unlock_bubble", (client: Client) => {
      const unlocked = unlockBubble(client.sessionId);
      client.send("bubble_lock_status", { locked: false });
      if (unlocked) {
        logger.info({ sessionId: client.sessionId }, "Bubble unlocked");
      }
    });

    this.throttledMessage("megaphone_start", (client: Client) => {
      if (this.isGuestBlocked(client, "megaphone")) return;
      handleMegaphoneStart(this.state, client, (type, payload) =>
        this.broadcast(type, payload)
      );
    });

    this.throttledMessage("megaphone_stop", (client: Client) => {
      handleMegaphoneStop(this.state, client, (type, payload) =>
        this.broadcast(type, payload)
      );
    });

    this.throttledMessage("spotlight_start", (client: Client) => {
      if (this.isGuestBlocked(client, "spotlight")) return;
      handleSpotlightStart(this.state, client, (type, payload) =>
        this.broadcast(type, payload)
      );
    });

    this.throttledMessage("spotlight_stop", (client: Client) => {
      handleSpotlightStop(client, this.state, (type, payload) =>
        this.broadcast(type, payload)
      );
    });

    this.throttledMessage("companion", (client: Client, message: { type: string }) => {
      handleCompanion(this.state, client, message);
    });

    this.throttledMessage("teleport", (client: Client, message: { targetSessionId: string }) => {
      handleTeleport(this.state, client, message);
    });

    this.throttledMessage(
      "draw_stroke",
      (client: Client, message: DrawStrokeMessage) => {
        handleWhiteboardDraw(this.state.whiteboards, client, message);
      },
    );

    this.throttledMessage(
      "clear_whiteboard",
      (client: Client, message: ClearWhiteboardMessage) => {
        handleWhiteboardClear(this.state.whiteboards, client, message);
      },
    );

    // Create default whiteboard
    const defaultWb = new WhiteboardSchema();
    defaultWb.id = "main";
    this.state.whiteboards.set("main", defaultWb);

    // Start proximity detection loop at 5Hz for WebRTC peer management
    this.stopProximityLoop = startProximityLoop(
      this.state,
      () => this.clients,
      5
    );

    logger.info(
      { departmentCount: DEFAULT_DEPARTMENTS.length },
      "Initialized with departments"
    );

    // Fire-and-forget: populate agents with retry logic.
    this.fetchAgentsWithRetry().catch((err) =>
      logger.error({ err }, "Failed to fetch agents after retries")
    );

    // Fire-and-forget: subscribe to real-time agent status updates via Redis.
    this.subscribeToAgentUpdates().catch((err) =>
      logger.error({ err }, "Failed to subscribe to agent updates")
    );
  }

  onJoin(client: Client, options?: OfficeJoinOptions & { name?: string }): void {
    const auth = client.auth as AuthResult | undefined;
    const isGuest = auth?.isGuest ?? false;
    const isDemoClient = auth?.isDemo ?? false;
    const playerName = auth?.name ?? options?.name ?? "Player";
    if (!this.roomOrgId && auth?.orgId) {
      this.roomOrgId = auth.orgId;
      this.fetchAgentsWithRetry().catch((err) =>
        logger.error({ err }, "Failed to fetch tenant agents after first join")
      );
    }

    logger.info(
      { sessionId: client.sessionId, isGuest, isDemo: isDemoClient, orgId: auth?.orgId },
      "Client joined",
    );

    const player = new TacticianSchema();
    player.sessionId = client.sessionId;
    player.name = playerName;
    player.x = 400;
    player.y = 300;
    player.direction = "down";
    player.isGuest = isGuest;
    this.state.players.set(client.sessionId, player);

    // Send LiveKit SFU credentials when configured so the client can
    // seamlessly switch from peer-to-peer to SFU mode when the room
    // exceeds the player threshold.
    if (isLiveKitEnabled()) {
      generateLiveKitToken(client.sessionId, playerName, this.roomId)
        .then((token) => {
          client.send("livekit_credentials", {
            url: getLiveKitUrl(),
            token,
          });
        })
        .catch((err) => {
          logger.warn({ err }, "Failed to generate LiveKit token");
        });
    }

    addSystemMessage(this.state, `${playerName} joined`, "office", this.getChatAuth(client));
    this.broadcast("player_joined", {
      sessionId: client.sessionId,
      name: playerName,
      isGuest,
    });

    // Start demo simulation on first demo client join
    if (isDemoClient && !this.demoSimulator) {
      this.demoSimulator = new DemoSimulator(this.state);
      this.demoSimulator.start();
    }
  }

  // @colyseus/core 0.17.x changed second arg from `consented: boolean` to
  // `code?: number` (the WebSocket close code). Code 1000 = normal close;
  // codes outside 1000-1999 indicate abnormal closure. The cleanup logic
  // below runs unconditionally — disconnect always means clean up — which
  // matches the prior consented=true path.
  override onLeave(client: Client, code?: number): void {
    logger.info(
      { sessionId: client.sessionId, closeCode: code },
      "Client left"
    );

    const player = this.state.players.get(client.sessionId);
    const name = player?.name ?? "Player";
    this.state.players.delete(client.sessionId);
    this.throttler.remove(client.sessionId);
    removeFromLockedGroups(client.sessionId);
    releaseMegaphone(client.sessionId, this.state, (type, payload) =>
      this.broadcast(type, payload)
    );
    releaseSpotlight(client.sessionId, this.state, (type, payload) =>
      this.broadcast(type, payload)
    );

    addSystemMessage(this.state, `${name} left`, "office", this.getChatAuth(client));
    this.broadcast("player_left", { sessionId: client.sessionId });
  }

  onDispose(): void {
    logger.info("Room disposed");
    if (this.demoSimulator) {
      this.demoSimulator.stop();
      this.demoSimulator = null;
    }
    if (this.stopProximityLoop) {
      this.stopProximityLoop();
      this.stopProximityLoop = null;
    }
    if (this.redisSubscriber) {
      this.redisSubscriber.quit().catch(() => {});
    }
  }

  // -- Agent sync from database -----------------------------------------------

  /**
   * Retry wrapper: attempts fetchAgentsFromApi with exponential backoff.
   * 3 immediate retries (1s, 2s, 4s), then a deferred retry after 30s.
   */
  private async fetchAgentsWithRetry(): Promise<void> {
    if (this.demoSimulator) return; // Demo agents are populated by the simulator
    if (!this.getServiceTenantOrg()) {
      logger.warn("No tenant org available for agent sync; skipping fetch");
      return;
    }
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        await this.fetchAgentsFromApi();
        return;
      } catch (err) {
        const delay = Math.pow(2, attempt - 1) * 1000;
        logger.warn(
          { attempt, maxAttempts, delay },
          "Agent fetch failed, retrying..."
        );
        if (attempt < maxAttempts) {
          await new Promise((r) => setTimeout(r, delay));
        }
      }
    }
    // All immediate retries failed — schedule a deferred retry.
    logger.warn("All agent fetch retries exhausted — scheduling deferred retry in 30s");
    setTimeout(() => {
      this.fetchAgentsFromApi().catch((err) =>
        logger.error({ err }, "Deferred agent fetch also failed")
      );
    }, 30_000);
  }

  private async fetchAgentsFromApi(): Promise<void> {
    const headers = this.getServiceAuthHeaders();
    if (!headers) {
      logger.warn("Missing service auth headers for tenant-scoped agent sync");
      return;
    }
    // Build a slug->colyseus-dept map for matching API departments to state.
    const slugToDept = new Map<string, { stateKey: string; dept: DepartmentSchema }>();
    this.state.departments.forEach((dept: DepartmentSchema, key: string) => {
      slugToDept.set(dept.slug, { stateKey: key, dept });
    });

    // Fetch the department list from the API (which uses real UUID IDs).
    let apiDepts: Array<Record<string, unknown>>;
    try {
      const listResp = await fetch(
        `${this.nexusApiUrl}/api/v1/departments/`,
        { headers }
      );
      if (!listResp.ok) {
        logger.error(
          { statusCode: listResp.status },
          "Failed to fetch department list"
        );
        return;
      }
      apiDepts = (await listResp.json()) as Array<Record<string, unknown>>;
    } catch (err) {
      logger.error({ err }, "Failed to fetch department list");
      throw err;
    }

    // For each API department, fetch its detail (with agents) and populate state.
    for (const apiDept of apiDepts) {
      const match = slugToDept.get(apiDept.slug as string);
      if (!match) continue;
      const { stateKey, dept } = match;

      try {
        const resp = await fetch(
          `${this.nexusApiUrl}/api/v1/departments/${apiDept.id}`,
          { headers }
        );
        if (!resp.ok) continue;
        const detail = (await resp.json()) as Record<string, unknown>;
        const agents = (detail.agents ?? []) as Array<Record<string, unknown>>;
        for (let i = 0; i < agents.length; i++) {
          const a = agents[i];
          const agent = new AgentSchema();
          agent.id = a.id as string;
          agent.name = a.name as string;
          agent.role = a.role as string;
          agent.status = (a.status as string) ?? "idle";
          agent.level = (a.level as number) ?? 1;
          agent.x = dept.x + 48 + (i % 3) * 48;
          agent.y = dept.y + 48 + Math.floor(i / 3) * 48;
          agent.currentTaskId = (a.current_task_id as string) ?? "";
          agent.currentTaskDescription = "";
          agent.departmentId = stateKey;
          const skills = (a.effective_skills ?? []) as string[];
          for (const skill of skills) {
            agent.skills.push(skill);
          }
          dept.agents.push(agent);
        }
        logger.info(
          { agentCount: agents.length, deptSlug: dept.slug, deptKey: stateKey },
          "Loaded agents into department"
        );
      } catch (err) {
        logger.error(
          { err, deptSlug: dept.slug },
          "Failed to fetch agents for department"
        );
      }
    }
    this.rebuildAgentIndex();
  }

  private async subscribeToAgentUpdates(): Promise<void> {
    if (this.demoSimulator) return; // No real agent updates in demo mode
    try {
      this.redisSubscriber = await getRedisClient();
    } catch (err) {
      logger.error(
        { err },
        "Redis subscriber failed to connect (room will work without real-time agent updates)"
      );
      return;
    }

    await this.redisSubscriber.subscribe(
      "selva:agent-status",
      (message: string) => {
        try {
          const update = JSON.parse(message) as {
            agent_id: string;
            status: string;
            task_id?: string;
            task_description?: string;
            current_node_id?: string;
          };
          this.updateAgentInState(
            update.agent_id,
            update.status,
            update.task_id,
            update.task_description,
            update.current_node_id
          );
        } catch (err) {
          logger.error({ err }, "Bad agent-status message");
        }
      }
    );
    logger.info("Subscribed to selva:agent-status channel");
  }

  private rebuildAgentIndex(): void {
    this.agentIndex.clear();
    this.state.departments.forEach((dept: DepartmentSchema, deptId: string) => {
      for (let i = 0; i < dept.agents.length; i++) {
        const agent = dept.agents.at(i);
        if (agent) {
          this.agentIndex.set(agent.id, { deptId, agentIndex: i });
        }
      }
    });
  }

  private updateAgentInState(
    agentId: string,
    status: string,
    taskId?: string,
    taskDescription?: string,
    currentNodeId?: string
  ): void {
    const applyUpdate = (agent: AgentSchema): void => {
      agent.status = status;
      if (taskId !== undefined) {
        agent.currentTaskId = taskId;
      }
      if (taskDescription !== undefined) {
        agent.currentTaskDescription = taskDescription;
      }
      if (currentNodeId !== undefined) {
        agent.currentNodeId = currentNodeId;
      }
      // Clear task fields when agent returns to idle
      if (status === "idle" && taskId === undefined) {
        agent.currentTaskId = "";
        agent.currentTaskDescription = "";
        agent.currentNodeId = "";
      }
      if (status === "waiting_approval") {
        this.state.pendingApprovalCount += 1;
        addSystemMessage(
          this.state,
          `Agent ${agent.name} is waiting for approval`,
          "office",
          this.getChatAuth()
        );
      }
    };

    const entry = this.agentIndex.get(agentId);
    if (entry) {
      const dept = this.state.departments.get(entry.deptId);
      const agent = dept?.agents.at(entry.agentIndex);
      if (agent && agent.id === agentId) {
        applyUpdate(agent);
        return;
      }
    }

    // Fallback: linear scan (index may be stale)
    let found = false;
    this.state.departments.forEach((dept: DepartmentSchema) => {
      if (found) return;
      for (let i = 0; i < dept.agents.length; i++) {
        const agent = dept.agents.at(i);
        if (agent && agent.id === agentId) {
          applyUpdate(agent);
          found = true;
          return;
        }
      }
    });

    if (!found) {
      logger.warn(
        { agentId },
        "Agent not found in any department"
      );
    }
  }
}
