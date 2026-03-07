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

export interface Player {
  sessionId: string;
  name: string;
  x: number;
  y: number;
  direction: 'up' | 'down' | 'left' | 'right';
}

export interface ChatMessage {
  id: string;
  senderSessionId: string;
  senderName: string;
  content: string;
  timestamp: number;
  isSystem: boolean;
}

export interface OfficeState {
  departments: Department[];
  reviewStations: ReviewStation[];
  players: Player[];
  localSessionId: string;
  activeAgentCount: number;
  pendingApprovalCount: number;
  chatMessages: ChatMessage[];
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
