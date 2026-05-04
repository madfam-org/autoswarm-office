'use client';

import { useCallback, useEffect, useState } from 'react';

import { apiFetch } from '@/lib/api';

/**
 * The five entries in the email-tool agent-slug allow-list. MUST stay
 * in sync with ``onboarding._AGENT_SLUG_ALLOWLIST`` (Python) and
 * ``email_tools._AGENT_ROLE_ALLOWLIST`` keys. Drift here means the UI
 * lets the tenant pick a slug that the email tool will then refuse at
 * send time. The backend re-validates on PUT so this is defense-in-depth,
 * not the only check.
 */
export const AGENT_SLUG_OPTIONS = [
  'sales',
  'support',
  'growth',
  'ops',
  'research',
] as const;

export type AgentSlug = (typeof AGENT_SLUG_OPTIONS)[number];

/**
 * Server-resolved outbound identity (matches Python
 * ``TenantIdentityResponse``). All fields are nullable individually —
 * the email tools fail-closed on missing pieces rather than substituting
 * defaults.
 */
export interface TenantIdentity {
  user_email: string | null;
  user_name: string | null;
  org_name: string | null;
  agent_slug: string | null;
}

/**
 * PUT payload (matches Python ``OutboundIdentityUpdate``). Submitting
 * a field as ``null`` clears the column; omitting a field leaves the
 * existing value untouched. ``undefined`` should be treated as "omit".
 */
export interface OutboundIdentityUpdate {
  outbound_user_email?: string | null;
  outbound_user_name?: string | null;
  outbound_agent_slug?: AgentSlug | null;
}

const ENDPOINT = '/api/v1/onboarding/tenant-identity';

export function useTenantIdentity() {
  const [identity, setIdentity] = useState<TenantIdentity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch(ENDPOINT);
      if (!resp.ok) {
        throw new Error(`status ${resp.status}`);
      }
      const data = (await resp.json()) as TenantIdentity;
      setIdentity(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'unknown');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const update = useCallback(
    async (body: OutboundIdentityUpdate): Promise<TenantIdentity> => {
      const resp = await apiFetch(ENDPOINT, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        // Surface the FastAPI error detail to the caller so the form
        // can show validation errors inline (e.g. invalid email format
        // returns 422 with the detail naming the field).
        let detail = `update failed: ${resp.status}`;
        try {
          const body = await resp.json();
          if (body?.detail) {
            detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
          }
        } catch {
          // body wasn't JSON — fall back to the generic message.
        }
        throw new Error(detail);
      }
      const data = (await resp.json()) as TenantIdentity;
      setIdentity(data);
      return data;
    },
    [],
  );

  return { identity, loading, error, refresh, update };
}
