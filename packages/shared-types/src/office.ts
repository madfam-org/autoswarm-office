import type { Agent } from './agent';

export interface Department {
  id: string;
  name: string;
  slug: string;
  description: string;
  agents: Agent[];
  maxAgents: number;
  position: { x: number; y: number };
}

export interface ReviewStation {
  id: string;
  departmentId: string;
  position: { x: number; y: number };
  pendingApprovals: number;
}

export interface TacticianPosition {
  x: number;
  y: number;
  direction: 'up' | 'down' | 'left' | 'right';
}

export interface OfficeState {
  departments: Department[];
  reviewStations: ReviewStation[];
  tactician: TacticianPosition;
  activeAgentCount: number;
  pendingApprovalCount: number;
}

export interface GamepadInput {
  leftStickX: number;
  leftStickY: number;
  rightStickX: number;
  rightStickY: number;
  buttonA: boolean;
  buttonB: boolean;
  buttonX: boolean;
  buttonY: boolean;
}
