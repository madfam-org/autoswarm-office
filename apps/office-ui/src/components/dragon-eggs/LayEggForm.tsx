'use client';

/**
 * Modal form for laying a new egg.
 *
 * Inline validation: persona_id (1-64 chars), platform (radio-pick
 * from Phase 1 scope), handle, display name, instance_url (Mastodon
 * only — surfaced conditionally so the form doesn't ask for it on
 * Bluesky/Reddit). Form posts via ``api.layEgg`` and bubbles success/
 * error back to the parent.
 */

import { useState } from 'react';

import { layEgg } from './api';
import {
  type EggDetail,
  type EggPlatform,
  PLATFORM_LABELS,
} from './types';

interface LayEggFormProps {
  onClose: () => void;
  onLaid: (egg: EggDetail) => void;
}

const PHASE_1_PLATFORMS: EggPlatform[] = ['mastodon', 'bluesky', 'reddit'];

export function LayEggForm({ onClose, onLaid }: LayEggFormProps) {
  const [platform, setPlatform] = useState<EggPlatform>('bluesky');
  const [personaId, setPersonaId] = useState('');
  const [handle, setHandle] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [instanceUrl, setInstanceUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requiresInstance = platform === 'mastodon';

  function validate(): string | null {
    if (!personaId.trim()) return 'persona_id is required';
    if (personaId.length > 64) return 'persona_id must be 64 chars or fewer';
    if (!handle.trim()) return 'handle is required';
    if (!displayName.trim()) return 'display_name is required';
    if (requiresInstance && !instanceUrl.trim()) {
      return 'instance_url is required for Mastodon';
    }
    return null;
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setSubmitting(true);
    try {
      const egg = await layEgg({
        persona_id: personaId.trim(),
        platform,
        handle: handle.trim(),
        display_name: displayName.trim(),
        instance_url: requiresInstance ? instanceUrl.trim() : null,
      });
      onLaid(egg);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to lay egg');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="lay-egg-title"
      onClick={onClose}
    >
      <form
        onSubmit={onSubmit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg space-y-5 rounded-md border border-slate-800 bg-slate-950 p-6 shadow-2xl"
      >
        <header className="space-y-1">
          <h2 id="lay-egg-title" className="text-lg font-semibold text-slate-100">
            Lay a new egg
          </h2>
          <p className="text-xs text-slate-400">
            Generates a 7-day warmup plan from the launch runbook §4.2.
          </p>
        </header>

        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-slate-400">
            Platform
          </legend>
          <div className="grid grid-cols-3 gap-2">
            {PHASE_1_PLATFORMS.map((p) => (
              <label
                key={p}
                className={`flex cursor-pointer items-center justify-center rounded-md border px-3 py-2 text-sm transition ${
                  platform === p
                    ? 'border-solarpunk-solar bg-solarpunk-solar/10 text-solarpunk-solar'
                    : 'border-slate-700 text-slate-300 hover:border-slate-600'
                }`}
              >
                <input
                  type="radio"
                  name="platform"
                  value={p}
                  checked={platform === p}
                  onChange={() => setPlatform(p)}
                  className="sr-only"
                />
                {PLATFORM_LABELS[p]}
              </label>
            ))}
          </div>
        </fieldset>

        <Field label="Persona ID" htmlFor="persona_id" hint="Matches MASTODON_ACCESS_TOKEN_<PERSONA_ID> env var convention.">
          <input
            id="persona_id"
            type="text"
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
            maxLength={64}
            required
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-solarpunk-solar focus:outline-none"
            placeholder="mx_compliance_voice"
          />
        </Field>

        <Field label="Display name" htmlFor="display_name">
          <input
            id="display_name"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-solarpunk-solar focus:outline-none"
            placeholder="MX Compliance Voice"
          />
        </Field>

        <Field label="Account handle" htmlFor="handle">
          <input
            id="handle"
            type="text"
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            required
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-solarpunk-solar focus:outline-none"
            placeholder={
              platform === 'reddit'
                ? 'u/mx_compliance'
                : platform === 'bluesky'
                ? '@handle.bsky.social'
                : '@handle@instance'
            }
          />
        </Field>

        {requiresInstance && (
          <Field label="Instance URL" htmlFor="instance_url" hint="Mastodon-only — full URL (https://fosstodon.org).">
            <input
              id="instance_url"
              type="url"
              value={instanceUrl}
              onChange={(e) => setInstanceUrl(e.target.value)}
              required={requiresInstance}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-solarpunk-solar focus:outline-none"
              placeholder="https://fosstodon.org"
            />
          </Field>
        )}

        {error && (
          <p className="rounded-md border border-semantic-error/40 bg-semantic-error-dark/20 px-3 py-2 text-xs text-semantic-error-light" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:border-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md border border-solarpunk-solar/60 bg-solarpunk-solar/10 px-4 py-2 text-sm font-medium text-solarpunk-solar hover:bg-solarpunk-solar/20 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solarpunk-solar"
          >
            {submitting ? 'Laying…' : 'Lay egg'}
          </button>
        </div>
      </form>
    </div>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}

function Field({ label, htmlFor, hint, children }: FieldProps) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}
