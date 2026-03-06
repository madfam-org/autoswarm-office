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
