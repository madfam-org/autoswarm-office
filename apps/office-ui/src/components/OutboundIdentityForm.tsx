'use client';

import { useCallback, useEffect, useState } from 'react';

import { useToast } from '@/hooks/useToast';
import {
  AGENT_SLUG_OPTIONS,
  type AgentSlug,
  type OutboundIdentityUpdate,
  type TenantIdentity,
  useTenantIdentity,
} from '@/hooks/useTenantIdentity';

/**
 * Conservative email shape check matching the backend regex
 * (``onboarding._EMAIL_RE`` and ``email_tools._EMAIL_RE``). Surfaces
 * client-side validation errors on blur so the user does not waste a
 * round-trip discovering the format is wrong. The backend re-validates
 * on PUT — this is UX, not security.
 */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const SLUG_LABELS: Record<AgentSlug | '', string> = {
  '': '(none — use default)',
  sales: 'Sales',
  support: 'Support',
  growth: 'Growth',
  ops: 'Operations',
  research: 'Research',
};

export function OutboundIdentityForm() {
  const { identity, loading, error, refresh, update } = useTenantIdentity();
  const { addToast } = useToast();

  // Form state mirrors the editable fields. Initialised from the
  // server's resolved identity but tracked separately so the user can
  // edit without immediately mutating the displayed "current" values.
  const [emailInput, setEmailInput] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [slugInput, setSlugInput] = useState<AgentSlug | ''>('');

  const [emailError, setEmailError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Re-seed the form from the server response whenever the identity
  // refreshes (initial load + post-submit reload).
  useEffect(() => {
    if (identity) {
      setEmailInput(identity.user_email ?? '');
      setNameInput(identity.user_name ?? '');
      // ``agent_slug`` may be a free-form legacy value if someone wrote
      // to the column directly. Only echo it into the dropdown when
      // it's a known slug — otherwise the dropdown shows "none" and the
      // user can pick a known value to clean it up.
      const slug = identity.agent_slug;
      setSlugInput(
        slug && (AGENT_SLUG_OPTIONS as readonly string[]).includes(slug)
          ? (slug as AgentSlug)
          : '',
      );
      setEmailError(null);
    }
  }, [identity]);

  const validateEmailOnBlur = useCallback(() => {
    if (!emailInput.trim()) {
      setEmailError(null);
      return;
    }
    if (!EMAIL_RE.test(emailInput.trim())) {
      setEmailError('Must be a valid email address (e.g. team@example.com)');
    } else {
      setEmailError(null);
    }
  }, [emailInput]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      // Re-validate inline before submit so the user sees the error
      // attached to the field, not just a toast.
      const trimmedEmail = emailInput.trim();
      if (trimmedEmail && !EMAIL_RE.test(trimmedEmail)) {
        setEmailError('Must be a valid email address (e.g. team@example.com)');
        return;
      }

      // Build the PUT payload. Empty strings → null (clears the column;
      // the backend's legacy fallback chain takes over). The slug
      // dropdown's empty-string option also clears the column.
      const body: OutboundIdentityUpdate = {
        outbound_user_email: trimmedEmail ? trimmedEmail : null,
        outbound_user_name: nameInput.trim() ? nameInput.trim() : null,
        outbound_agent_slug: slugInput ? slugInput : null,
      };

      setSubmitting(true);
      try {
        await update(body);
        addToast('Outbound identity updated', 'success');
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'update failed';
        addToast(msg, 'error');
      } finally {
        setSubmitting(false);
      }
    },
    [emailInput, nameInput, slugInput, update, addToast],
  );

  if (loading && !identity) {
    return <p className="text-slate-400">Loading outbound identity…</p>;
  }

  if (error && !identity) {
    return (
      <div className="space-y-2">
        <p className="text-red-300">Could not load outbound identity: {error}</p>
        <button
          type="button"
          onClick={refresh}
          className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 hover:bg-slate-800"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5"
      aria-labelledby="outbound-identity-heading"
    >
      <div className="space-y-2">
        <label
          htmlFor="outbound-user-email"
          className="block text-sm font-semibold text-slate-200"
        >
          Outbound mailbox
        </label>
        <input
          id="outbound-user-email"
          type="email"
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
          onBlur={validateEmailOnBlur}
          maxLength={255}
          placeholder="team@yourcompany.com"
          aria-invalid={emailError ? 'true' : 'false'}
          aria-describedby={emailError ? 'outbound-user-email-error' : 'outbound-user-email-help'}
          disabled={submitting}
          className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 disabled:opacity-50"
        />
        {emailError ? (
          <p id="outbound-user-email-error" className="text-xs text-red-400" role="alert">
            {emailError}
          </p>
        ) : (
          <p id="outbound-user-email-help" className="text-xs text-slate-500">
            Drives the From: address in user_direct + dyad voice modes.
            Leave blank to fall back to your tenant's primary contact email.
          </p>
        )}
      </div>

      <div className="space-y-2">
        <label
          htmlFor="outbound-user-name"
          className="block text-sm font-semibold text-slate-200"
        >
          Display name
        </label>
        <input
          id="outbound-user-name"
          type="text"
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          maxLength={255}
          placeholder="Your Company Team"
          aria-describedby="outbound-user-name-help"
          disabled={submitting}
          className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 disabled:opacity-50"
        />
        <p id="outbound-user-name-help" className="text-xs text-slate-500">
          Display name shown alongside the address in the From: header.
          Falls back to your white-label brand or legal name when empty.
        </p>
      </div>

      <div className="space-y-2">
        <label
          htmlFor="outbound-agent-slug"
          className="block text-sm font-semibold text-slate-200"
        >
          Pinned agent slug
        </label>
        <select
          id="outbound-agent-slug"
          value={slugInput}
          onChange={(e) => setSlugInput(e.target.value as AgentSlug | '')}
          aria-describedby="outbound-agent-slug-help"
          disabled={submitting}
          className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 disabled:opacity-50"
        >
          {(['', ...AGENT_SLUG_OPTIONS] as const).map((opt) => (
            <option key={opt} value={opt}>
              {SLUG_LABELS[opt]}
            </option>
          ))}
        </select>
        <p id="outbound-agent-slug-help" className="text-xs text-slate-500">
          Only used by agent_identified voice mode. Constrains outbound
          sends to <code>{'<slug>'}-agent@selva.town</code>. Choose
          "(none)" to let each call pick its own role-appropriate slug.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Save changes'}
        </button>
        {identity && (
          <span className="text-xs text-slate-500">
            Currently resolved: {identity.user_email ?? '(no email)'} ·{' '}
            {identity.user_name ?? '(no name)'}
          </span>
        )}
      </div>
    </form>
  );
}
