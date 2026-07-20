import { apiFetch } from '@/lib/api';

import type {
  CampaignSocialScheduleRequest,
  CrmCampaignHandoffRequest,
  CrmCampaignHandoffResponse,
  ScheduledActionBatchResponse,
  ScheduledActionRow,
  TulanaFeedbackRequest,
  TulanaFeedbackResponse,
  TulanaImportRequest,
  TulanaImportResponse,
} from './types';

async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string | { message?: string } };
      if (typeof body?.detail === 'string') {
        detail = body.detail;
      } else if (body?.detail && typeof body.detail === 'object' && body.detail.message) {
        detail = body.detail.message;
      }
    } catch {
      // fall back to status line
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function importTulanaPacks(
  body: TulanaImportRequest,
  idempotencyKey?: string,
): Promise<TulanaImportResponse> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const r = await apiFetch('/api/v1/campaigns/import-tulana-pack', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return parseOrThrow<TulanaImportResponse>(r);
}

export async function crmCampaignHandoff(
  body: CrmCampaignHandoffRequest,
  idempotencyKey?: string,
): Promise<CrmCampaignHandoffResponse> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const r = await apiFetch('/api/v1/campaigns/crm-handoff', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return parseOrThrow<CrmCampaignHandoffResponse>(r);
}

export async function scheduleCampaignSocial(
  body: CampaignSocialScheduleRequest,
  idempotencyKey?: string,
): Promise<ScheduledActionBatchResponse> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const r = await apiFetch('/api/v1/campaigns/schedule-social', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return parseOrThrow<ScheduledActionBatchResponse>(r);
}

export async function pushTulanaFeedback(
  body: TulanaFeedbackRequest,
  idempotencyKey?: string,
): Promise<TulanaFeedbackResponse> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const r = await apiFetch('/api/v1/campaigns/tulana-feedback', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return parseOrThrow<TulanaFeedbackResponse>(r);
}

export async function listScheduledActions(status?: string): Promise<ScheduledActionRow[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const query = params.toString();
  const r = await apiFetch(`/api/v1/scheduled-actions${query ? `?${query}` : ''}`);
  return parseOrThrow<ScheduledActionRow[]>(r);
}

export async function updateScheduledActionHitl(
  actionId: string,
  decision: 'approved' | 'denied',
): Promise<ScheduledActionRow> {
  const r = await apiFetch(`/api/v1/scheduled-actions/${actionId}/hitl`, {
    method: 'PATCH',
    body: JSON.stringify({ decision }),
  });
  return parseOrThrow<ScheduledActionRow>(r);
}

// -- PhyndCRM campaign authorizations (owner money-gate) ----------------------

export async function listPendingAuthorizations(): Promise<
  import('./types').PendingAuthorizationRow[]
> {
  const r = await apiFetch('/api/v1/campaigns/authorizations/pending');
  const body = await parseOrThrow<{ pending: import('./types').PendingAuthorizationRow[] }>(r);
  return body.pending;
}

export async function getAuthorizationPreview(
  authorizationId: string,
): Promise<import('./types').AuthorizationPreview> {
  const r = await apiFetch(
    `/api/v1/campaigns/authorizations/${encodeURIComponent(authorizationId)}/preview`,
  );
  return parseOrThrow<import('./types').AuthorizationPreview>(r);
}

export async function decideAuthorization(
  authorizationId: string,
  decision: 'authorized' | 'rejected',
  note?: string,
): Promise<import('./types').AuthorizationRecord> {
  const r = await apiFetch(
    `/api/v1/campaigns/authorizations/${encodeURIComponent(authorizationId)}/decide`,
    { method: 'POST', body: JSON.stringify({ decision, note: note || undefined }) },
  );
  return parseOrThrow<import('./types').AuthorizationRecord>(r);
}

export async function requestFreshAuthorization(
  campaignId: string,
): Promise<import('./types').AuthorizationRecord> {
  const r = await apiFetch('/api/v1/campaigns/authorizations/request', {
    method: 'POST',
    body: JSON.stringify({ campaign_id: campaignId }),
  });
  return parseOrThrow<import('./types').AuthorizationRecord>(r);
}
