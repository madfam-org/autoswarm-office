'use client';

import { useCallback, useState } from 'react';

import {
  crmCampaignHandoff,
  importTulanaPacks,
  pushTulanaFeedback,
  scheduleCampaignSocial,
} from '@/components/campaigns/api';
import type {
  CampaignSocialScheduleRequest,
  CrmCampaignHandoffRequest,
  CrmCampaignHandoffResponse,
  ScheduledActionBatchResponse,
  TulanaFeedbackRequest,
  TulanaFeedbackResponse,
  TulanaImportRequest,
  TulanaImportResponse,
  TulanaSkuCampaignPack,
} from '@/components/campaigns/types';

type CampaignOpStatus = 'idle' | 'loading' | 'success' | 'error';

interface CampaignsState {
  status: CampaignOpStatus;
  error: string | null;
  lastImport: TulanaImportResponse | null;
  lastHandoff: CrmCampaignHandoffResponse | null;
  lastSchedule: ScheduledActionBatchResponse | null;
  lastFeedback: TulanaFeedbackResponse | null;
  importPacks: (
    request: TulanaImportRequest,
    idempotencyKey?: string,
  ) => Promise<TulanaImportResponse | null>;
  submitHandoff: (
    request: CrmCampaignHandoffRequest,
    idempotencyKey?: string,
  ) => Promise<CrmCampaignHandoffResponse | null>;
  submitSchedule: (
    request: CampaignSocialScheduleRequest,
    idempotencyKey?: string,
  ) => Promise<ScheduledActionBatchResponse | null>;
  submitFeedback: (
    request: TulanaFeedbackRequest,
    idempotencyKey?: string,
  ) => Promise<TulanaFeedbackResponse | null>;
  reset: () => void;
}

export function useCampaigns(): CampaignsState {
  const [status, setStatus] = useState<CampaignOpStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastImport, setLastImport] = useState<TulanaImportResponse | null>(null);
  const [lastHandoff, setLastHandoff] = useState<CrmCampaignHandoffResponse | null>(null);
  const [lastSchedule, setLastSchedule] = useState<ScheduledActionBatchResponse | null>(null);
  const [lastFeedback, setLastFeedback] = useState<TulanaFeedbackResponse | null>(null);

  const run = useCallback(
    async <T,>(fn: () => Promise<T>, onSuccess: (value: T) => void): Promise<T | null> => {
      setStatus('loading');
      setError(null);
      try {
        const result = await fn();
        onSuccess(result);
        setStatus('success');
        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Campaign request failed';
        setError(message);
        setStatus('error');
        return null;
      }
    },
    [],
  );

  const importPacks = useCallback(
    (request: TulanaImportRequest, idempotencyKey?: string) =>
      run(() => importTulanaPacks(request, idempotencyKey), setLastImport),
    [run],
  );

  const submitHandoff = useCallback(
    (request: CrmCampaignHandoffRequest, idempotencyKey?: string) =>
      run(() => crmCampaignHandoff(request, idempotencyKey), setLastHandoff),
    [run],
  );

  const submitSchedule = useCallback(
    (request: CampaignSocialScheduleRequest, idempotencyKey?: string) =>
      run(() => scheduleCampaignSocial(request, idempotencyKey), setLastSchedule),
    [run],
  );

  const submitFeedback = useCallback(
    (request: TulanaFeedbackRequest, idempotencyKey?: string) =>
      run(() => pushTulanaFeedback(request, idempotencyKey), setLastFeedback),
    [run],
  );

  const reset = useCallback(() => {
    setStatus('idle');
    setError(null);
    setLastImport(null);
    setLastHandoff(null);
    setLastSchedule(null);
    setLastFeedback(null);
  }, []);

  return {
    status,
    error,
    lastImport,
    lastHandoff,
    lastSchedule,
    lastFeedback,
    importPacks,
    submitHandoff,
    submitSchedule,
    submitFeedback,
    reset,
  };
}

/** Parse pasted JSON into Tulana packs (array or { packs: [...] }). */
export function parseTulanaImportJson(raw: string): TulanaSkuCampaignPack[] {
  const parsed = JSON.parse(raw) as unknown;
  if (Array.isArray(parsed)) {
    return parsed as TulanaSkuCampaignPack[];
  }
  if (
    parsed &&
    typeof parsed === 'object' &&
    Array.isArray((parsed as { packs?: unknown }).packs)
  ) {
    return (parsed as { packs: TulanaSkuCampaignPack[] }).packs;
  }
  throw new Error('Expected a JSON array of packs or { "packs": [...] }');
}
