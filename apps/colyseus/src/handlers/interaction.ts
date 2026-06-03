import { Client } from "@colyseus/core";
import { OfficeStateSchema, AgentSchema } from "../schema/OfficeState";
import { createLogger } from "@selva/config/logging";

const logger = createLogger({ service: "colyseus" }).child({ component: "interaction" });

interface InteractData {
  agentId: string;
}

interface ApprovalData {
  requestId: string;
  result: "approved" | "denied";
  feedback?: string;
  nexusApiUrl: string;
}

function findAgent(
  state: OfficeStateSchema,
  agentId: string
): AgentSchema | null {
  let found: AgentSchema | null = null;

  state.departments.forEach((dept) => {
    for (let i = 0; i < dept.agents.length; i++) {
      const agent = dept.agents.at(i);
      if (agent && agent.id === agentId) {
        found = agent;
      }
    }
  });

  return found;
}

export function handleInteraction(
  state: OfficeStateSchema,
  client: Client,
  data: InteractData
): void {
  const { agentId } = data;

  if (!agentId) {
    client.send("error", {
      type: "invalid_interaction",
      message: "agentId is required",
    });
    return;
  }

  const agent = findAgent(state, agentId);

  if (!agent) {
    client.send("error", {
      type: "agent_not_found",
      message: `Agent ${agentId} not found in any department`,
    });
    return;
  }

  if (agent.status === "waiting_approval") {
    client.send("show_approval_modal", {
      agentId: agent.id,
      agentName: agent.name,
      agentRole: agent.role,
      level: agent.level,
    });
    logger.info(
      { agentName: agent.name, sessionId: client.sessionId },
      "Agent has pending approval; prompting client"
    );
    return;
  }

  client.send("agent_info", {
    id: agent.id,
    name: agent.name,
    role: agent.role,
    status: agent.status,
    level: agent.level,
    x: agent.x,
    y: agent.y,
  });
  logger.info(
    { agentName: agent.name, agentStatus: agent.status },
    "Showing agent info"
  );
}

export async function handleApproval(
  state: OfficeStateSchema,
  client: Client,
  data: ApprovalData
): Promise<void> {
  const { requestId, result, feedback, nexusApiUrl } = data;

  if (!requestId || !result) {
    client.send("error", {
      type: "invalid_approval",
      message: "requestId and result are required",
    });
    return;
  }

  try {
    const action = result === "approved" ? "approve" : "deny";
    const response = await fetch(
      `${nexusApiUrl}/api/v1/approvals/${requestId}/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback: feedback ?? null }),
      }
    );

    if (!response.ok) {
      const errorBody = await response.text();
      logger.error(
        { requestId, statusCode: response.status, errorBody },
        "Nexus API returned error for approval"
      );
      client.send("approval_error", {
        requestId,
        message: `Nexus API error: ${response.status}`,
      });
      return;
    }

    const responseData = (await response.json()) as Record<string, unknown>;

    const agentId =
      typeof responseData.agentId === "string" ? responseData.agentId : null;

    if (agentId) {
      const agent = findAgent(state, agentId);
      if (agent) {
        agent.status = result === "approved" ? "working" : "idle";
      }
    }

    if (state.pendingApprovalCount > 0) {
      state.pendingApprovalCount -= 1;
    }

    client.send("approval_confirmed", {
      requestId,
      result,
    });

    logger.info(
      { requestId, result, feedback: feedback ?? null },
      "Approval processed"
    );
  } catch (err) {
    logger.error({ err, requestId }, "Failed to forward approval to nexus-api");
    client.send("approval_error", {
      requestId,
      message: "Failed to communicate with nexus-api",
    });
  }
}
