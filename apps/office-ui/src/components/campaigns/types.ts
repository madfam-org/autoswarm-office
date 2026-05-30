/** Wire types for Tulana campaign orchestration (Phase 2.7). */

export type GaReadiness = 'near_ready' | 'waived' | 'blocked' | 'ready' | 'discovery';

export type PolicyState =
  | 'approved'
  | 'waived_by_operator'
  | 'blocked'
  | 'pending_review'
  | string;

export interface TulanaProofPoint {
  label: string;
  source: string;
  url?: string | null;
}

export interface TulanaSkuCampaignPack {
  generated_at?: string | null;
  sku_key: string;
  platform?: string;
  audience: string;
  ga_readiness: GaReadiness;
  rank?: number | null;
  readiness_reasons?: string[];
  value_prop?: string;
  proof_points?: TulanaProofPoint[];
  do_not_claim?: string[];
  policy_state?: PolicyState;
  last_verified_at: string;
}

export interface TulanaImportRequest {
  packs: TulanaSkuCampaignPack[];
  allow_blocked?: boolean;
  dispatch_tasks?: boolean;
}

export interface TulanaPackValidation {
  sku_key: string;
  accepted: boolean;
  errors: string[];
  rank_score?: number | null;
}

export interface TulanaImportResponse {
  accepted: TulanaSkuCampaignPack[];
  rejected: TulanaPackValidation[];
  ranked_sku_keys: string[];
  dispatched_task_ids: string[];
}

export interface CrmCampaignHandoffRequest {
  sku_key: string;
  audience: string;
  draft_variants: string[];
  tulana_pack: TulanaSkuCampaignPack;
  campaign_name?: string | null;
  phynd_list_id?: string | null;
}

export interface CrmCampaignHandoffResponse {
  handoff_id: string;
  task_id: string;
  status: string;
  message: string;
}

export type SocialPlatform = 'mastodon' | 'bluesky' | 'reddit' | 'email';

export interface CampaignSocialPostItem {
  scheduled_for: string;
  payload: Record<string, unknown>;
}

export interface CampaignSocialScheduleRequest {
  sku_key: string;
  platform: SocialPlatform;
  posts: CampaignSocialPostItem[];
  playbook_id?: string | null;
  persona_id?: string | null;
  campaign_id?: string | null;
  require_hitl?: boolean;
}

export interface ScheduledActionRow {
  id: string;
  action_type: string;
  scheduled_for: string;
  status: string;
  payload: Record<string, unknown>;
  playbook_id: string | null;
  hitl_status: string | null;
  persona_id: string | null;
  org_id: string;
  retry_count: number;
  max_retries: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledActionBatchResponse {
  created: ScheduledActionRow[];
  count: number;
}

export interface TulanaBuyerSignal {
  metric: string;
  value: string | number;
  source?: string;
}

export interface TulanaFeedbackRequest {
  sku_key: string;
  summary: string;
  outcomes: TulanaBuyerSignal[];
  campaign_name?: string | null;
  handoff_id?: string | null;
  task_id?: string | null;
  evidence_urls?: string[];
}

export interface TulanaFeedbackResponse {
  status: string;
  tulana_event_id: string | null;
  message: string;
}
