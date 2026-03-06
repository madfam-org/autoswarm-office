import { Client } from "@colyseus/core";
import { OfficeStateSchema, AgentSchema } from "../schema/OfficeState";

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

interface MoveData {
  x: number;
  y: number;
}

interface ProximityResult {
  agent: AgentSchema;
  distance: number;
}

const OFFICE_BOUNDS: Bounds = {
  minX: 0,
  minY: 0,
  maxX: 800,
  maxY: 600,
};

const DEFAULT_PROXIMITY_THRESHOLD = 64;

export function validatePosition(
  x: number,
  y: number,
  bounds: Bounds = OFFICE_BOUNDS
): boolean {
  if (typeof x !== "number" || typeof y !== "number") {
    return false;
  }
  if (isNaN(x) || isNaN(y)) {
    return false;
  }
  return (
    x >= bounds.minX &&
    x <= bounds.maxX &&
    y >= bounds.minY &&
    y <= bounds.maxY
  );
}

export function handleMovement(
  state: OfficeStateSchema,
  client: Client,
  data: MoveData
): void {
  const { x, y } = data;

  if (!validatePosition(x, y)) {
    client.send("error", {
      type: "invalid_position",
      message: `Position (${x}, ${y}) is out of bounds`,
    });
    return;
  }

  const prevX = state.tactician.x;
  const prevY = state.tactician.y;

  state.tactician.x = x;
  state.tactician.y = y;

  const dx = x - prevX;
  const dy = y - prevY;

  if (Math.abs(dx) > Math.abs(dy)) {
    state.tactician.direction = dx > 0 ? "right" : "left";
  } else if (dy !== 0) {
    state.tactician.direction = dy > 0 ? "down" : "up";
  }

  const allAgents: AgentSchema[] = [];
  state.departments.forEach((dept) => {
    for (let i = 0; i < dept.agents.length; i++) {
      allAgents.push(dept.agents[i]);
    }
  });

  const nearby = checkProximity(
    state.tactician,
    allAgents,
    DEFAULT_PROXIMITY_THRESHOLD
  );

  if (nearby.length > 0) {
    client.send("nearby_agents", {
      agents: nearby.map((result) => ({
        id: result.agent.id,
        name: result.agent.name,
        role: result.agent.role,
        status: result.agent.status,
        distance: Math.round(result.distance),
      })),
    });
  }
}

export function checkProximity(
  tactician: { x: number; y: number },
  agents: AgentSchema[],
  threshold: number = DEFAULT_PROXIMITY_THRESHOLD
): ProximityResult[] {
  const results: ProximityResult[] = [];

  for (const agent of agents) {
    const dx = tactician.x - agent.x;
    const dy = tactician.y - agent.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance <= threshold) {
      results.push({ agent, distance });
    }
  }

  results.sort((a, b) => a.distance - b.distance);

  return results;
}
