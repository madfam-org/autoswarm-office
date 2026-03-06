export interface ComputeTokenBucket {
  dailyLimit: number;
  used: number;
  remaining: number;
  resetAt: string;
}

export type SubscriptionTier = 'starter' | 'professional' | 'enterprise';

export interface TierCapabilities {
  tier: SubscriptionTier;
  maxAgents: number;
  maxDepartments: number;
  dailyComputeTokens: number;
  maxConcurrentTasks: number;
  features: string[];
}

export interface SubscriptionCapabilities {
  tier: SubscriptionTier;
  capabilities: TierCapabilities;
  computeTokens: ComputeTokenBucket;
  isActive: boolean;
}
