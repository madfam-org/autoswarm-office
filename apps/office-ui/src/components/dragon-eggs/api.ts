/**
 * Thin wrappers around ``apiFetch`` for the dragon-egg endpoints.
 *
 * The shared ``apiFetch`` already attaches the Janua bearer token,
 * sets Content-Type, and handles credentials. We only add JSON
 * parsing + error normalization on top.
 */

import { apiFetch } from '@/lib/api';

import type { Egg, EggDetail, LayEggRequest } from './types';

async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // body wasn't JSON — fall back to status line.
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as unknown as T;
  }
  return (await response.json()) as T;
}

export async function listEggs(filters?: {
  status?: string;
  platform?: string;
}): Promise<Egg[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.platform) params.set('platform', filters.platform);
  const query = params.toString();
  const path = `/api/v1/dragon-eggs${query ? `?${query}` : ''}`;
  const r = await apiFetch(path);
  return parseOrThrow<Egg[]>(r);
}

export async function getEgg(id: string): Promise<EggDetail> {
  const r = await apiFetch(`/api/v1/dragon-eggs/${id}`);
  return parseOrThrow<EggDetail>(r);
}

export async function layEgg(body: LayEggRequest): Promise<EggDetail> {
  const r = await apiFetch('/api/v1/dragon-eggs', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return parseOrThrow<EggDetail>(r);
}

export async function transitionEgg(id: string): Promise<{ egg: Egg; transitioned: boolean }> {
  const r = await apiFetch(`/api/v1/dragon-eggs/${id}/transition`, { method: 'POST' });
  return parseOrThrow<{ egg: Egg; transitioned: boolean }>(r);
}

export async function executeAction(eggId: string, actionId: string) {
  const r = await apiFetch(
    `/api/v1/dragon-eggs/${eggId}/actions/${actionId}/execute`,
    { method: 'POST' },
  );
  return parseOrThrow(r);
}

export async function skipAction(eggId: string, actionId: string, notes?: string) {
  const r = await apiFetch(`/api/v1/dragon-eggs/${eggId}/actions/${actionId}/skip`, {
    method: 'POST',
    body: JSON.stringify({ notes: notes ?? null }),
  });
  return parseOrThrow(r);
}

export async function releaseEgg(id: string, forceStatus?: string): Promise<void> {
  const params = forceStatus ? `?force_status=${encodeURIComponent(forceStatus)}` : '';
  const r = await apiFetch(`/api/v1/dragon-eggs/${id}${params}`, { method: 'DELETE' });
  await parseOrThrow<void>(r);
}
