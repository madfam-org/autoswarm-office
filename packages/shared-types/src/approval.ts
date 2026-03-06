export type PermissionLevel = 'allow' | 'ask' | 'deny';

export type ActionCategory =
  | 'file_read'
  | 'file_write'
  | 'bash_execute'
  | 'git_commit'
  | 'git_push'
  | 'email_send'
  | 'crm_update'
  | 'deploy'
  | 'api_call';

export interface ApprovalRequest {
  id: string;
  agentId: string;
  agentName: string;
  actionCategory: ActionCategory;
  actionType: string;
  payload: Record<string, unknown>;
  diff?: string;
  reasoning: string;
  urgency: 'low' | 'medium' | 'high' | 'critical';
  createdAt: string;
}

export interface ApprovalResponse {
  requestId: string;
  result: 'approved' | 'denied';
  feedback?: string;
  respondedAt: string;
}

export type PermissionMatrix = Record<ActionCategory, PermissionLevel>;
