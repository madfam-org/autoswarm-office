// CONVENTION: camelCase fields. These types are the domain shape used
// inside React + Phaser code; wire payloads (snake_case from the Python
// API) are converted at the fetch boundary in
// `apps/office-ui/src/lib/api.ts`. Keep this file in sync with that
// converter — the Colyseus AgentSchema field names also match this shape.

export type AgentRole = 'planner' | 'coder' | 'reviewer' | 'researcher' | 'crm' | 'support';

export type AgentStatus = 'idle' | 'working' | 'waiting_approval' | 'paused' | 'error';

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  level: number;
  departmentId: string | null;
  currentTaskId: string | null;
  currentNodeId?: string;
  synergyBonuses: SynergyBonus[];
  createdAt: string;
  updatedAt: string;
}

export interface SynergyBonus {
  name: string;
  description: string;
  multiplier: number;
  requiredRoles: AgentRole[];
}
