'use client';

import Link from 'next/link';

import { OutboundIdentityForm } from '@/components/OutboundIdentityForm';
import { ToastProvider } from '@/components/Toast';

/**
 * Tenant settings — outbound identity (Phase 2 of the v2.2.x email
 * lockdown remediation).
 *
 * Lets a tenant configure ``outbound_user_email``, ``outbound_user_name``,
 * and ``outbound_agent_slug`` on their ``tenant_configs`` row without
 * needing MADFAM ops to populate ``tenant_identities``. Closes the
 * regression where new tenants got "Tenant outbound identity not
 * configured" on every email send.
 */
export default function OutboundIdentitySettingsPage() {
  return (
    <ToastProvider>
      <main className="min-h-screen bg-slate-950 px-6 py-12 text-slate-100">
        <div className="mx-auto max-w-2xl space-y-6">
          <header className="space-y-2">
            <Link
              href="/office"
              className="text-xs text-indigo-400 hover:text-indigo-300"
            >
              &larr; Back to office
            </Link>
            <h1 id="outbound-identity-heading" className="text-2xl font-bold">
              Outbound identity
            </h1>
            <p className="text-slate-400">
              Configure how your agents identify themselves when they send
              email on your behalf. These values feed the From: header
              after the voice-mode gate runs.
            </p>
          </header>

          <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6">
            <OutboundIdentityForm />
          </section>

          <p className="text-xs text-slate-500">
            Empty fields fall back to your tenant&apos;s legacy chain
            (brand name, legal name, primary contact email). The voice
            mode itself is configured separately under{' '}
            <Link href="/onboarding" className="text-indigo-400 hover:text-indigo-300">
              voice-mode onboarding
            </Link>
            .
          </p>
        </div>
      </main>
    </ToastProvider>
  );
}
