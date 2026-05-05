/**
 * Shared TypeScript types for the dragon-egg surface.
 *
 * Mirrors the FastAPI Pydantic schemas in
 * ``apps/nexus-api/nexus_api/routers/dragon_eggs.py``. A future PR
 * will move these into ``packages/shared-types`` so the backend
 * Pydantic and frontend TypeScript can stay in lockstep — for Phase 1
 * this single file is the source of truth on the frontend.
 */

export type EggPlatform = 'mastodon' | 'bluesky' | 'reddit';

export type EggStatus =
  | 'laid'
  | 'incubating'
  | 'hatching'
  | 'hatched'
  | 'matured';

export type ActionStatus =
  | 'planned'
  | 'pending_human'
  | 'in_flight'
  | 'completed'
  | 'failed'
  | 'skipped';

export type ActionType =
  | 'profile_setup'
  | 'follow_curated'
  | 'boost_high_signal'
  | 'reply_substantive'
  | 'original_post_no_link'
  | 'original_post_with_link'
  | 'promotional_post';

export interface WarmupAction {
  id: string;
  egg_id: string;
  action_type: ActionType;
  status: ActionStatus;
  scheduled_for: string;
  executed_at: string | null;
  result: Record<string, unknown> | null;
  day_offset: number;
  notes: string | null;
  content_brief: string | null;
}

export interface Egg {
  id: string;
  persona_id: string;
  platform: EggPlatform;
  display_name: string;
  handle: string;
  instance_url: string | null;
  status: EggStatus;
  progress: number;
  laid_at: string;
  hatched_at: string | null;
  matured_at: string | null;
  owner_org_id: string;
  created_by: string;
  metadata: Record<string, unknown>;
}

export interface EggDetail extends Egg {
  actions: WarmupAction[];
}

export interface LayEggRequest {
  persona_id: string;
  platform: EggPlatform;
  handle: string;
  display_name: string;
  instance_url?: string | null;
  metadata?: Record<string, unknown>;
}

/** Stage display order — used by UI sort + EggArt component selection. */
export const EGG_STATUS_ORDER: readonly EggStatus[] = [
  'laid',
  'incubating',
  'hatching',
  'hatched',
  'matured',
] as const;

/** Operator-facing labels — playful but operator-grade. */
export const EGG_STATUS_LABELS: Record<EggStatus, string> = {
  laid: 'Laid',
  incubating: 'Incubating',
  hatching: 'Hatching',
  hatched: 'Hatched',
  matured: 'Matured',
};

export const PLATFORM_LABELS: Record<EggPlatform, string> = {
  mastodon: 'Mastodon',
  bluesky: 'Bluesky',
  reddit: 'Reddit',
};

export const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  profile_setup: 'Profile setup',
  follow_curated: 'Follow curated',
  boost_high_signal: 'Boost high-signal',
  reply_substantive: 'Reply substantive',
  original_post_no_link: 'Original post (no link)',
  original_post_with_link: 'Original post (with link)',
  promotional_post: 'Promotional post',
};

export const ACTION_STATUS_LABELS: Record<ActionStatus, string> = {
  planned: 'Planned',
  pending_human: 'Pending human',
  in_flight: 'In flight',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
};
