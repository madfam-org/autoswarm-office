// CONVENTION: camelCase fields. These types are the domain shape used
// inside React + Phaser code; wire payloads (snake_case from the Python
// API) are converted at the fetch boundary in
// `apps/office-ui/src/lib/api.ts`. The Colyseus state schemas in
// `apps/colyseus/src/schema/` mirror these names.

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

/**
 * Companion sprite a player can attach to their avatar. Empty string means
 * no companion. The literal list MUST stay in sync with the server-side
 * whitelist in `apps/colyseus/src/handlers/companion.ts`.
 */
export type CompanionType = '' | 'cat' | 'dog' | 'robot' | 'dragon' | 'parrot';

export interface Player {
  sessionId: string;
  name: string;
  x: number;
  y: number;
  direction: 'up' | 'down' | 'left' | 'right';
  avatarConfig?: string;
  playerStatus?: 'online' | 'away' | 'busy' | 'dnd';
  companionType?: CompanionType;
  /** Free-text mood/music status. Server enforces max 50 characters. */
  musicStatus?: string;
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
