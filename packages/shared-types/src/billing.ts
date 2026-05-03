// CONVENTION: camelCase fields. Domain shape used by React; the Dhanam
// billing API responses are converted at the fetch boundary in
// `apps/office-ui/src/lib/api.ts`.

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
