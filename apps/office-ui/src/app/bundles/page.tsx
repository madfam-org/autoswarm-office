/**
 * selva.town/bundles — proposed ecosystem bundles.
 *
 * Three bundles from PRICING_OVERHAUL_20260417.md section 4:
 *   - Founder   (indie / solo operator)
 *   - Operator  (mid-market team)
 *   - Flywheel Suite (enterprise / full stack)
 *
 * Live à-la-carte total pulled from Dhanam's public billing catalog
 * so the savings math stays honest as list prices change.
 *
 * VISIBILITY: admin-only. Route is guarded by a server-side role check
 * (see below). Non-admins hitting /bundles are redirected to /office.
 * Rationale: bundle SKUs are still a PROPOSED pricing surface — we want
 * internal operators to review the math before making it a public page.
 *
 * When bundle SKUs are modelled as first-class Dhanam products (parent/
 * child tier shapes in sync-catalog.ts), drop the admin gate and this
 * becomes a public marketing page.
 */
import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import Link from 'next/link';

import {
  type BundleLine,
  type CatalogResponse,
  type ResolvedLine,
  computeSavings,
  fmtUsd,
  resolveLine,
  sumMonthlyUsd,
} from './helpers';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Selva — MADFAM Ecosystem Bundles',
  description:
    'Three curated MADFAM product bundles — Founder, Operator, Flywheel Suite — with live à-la-carte totals.',
};

interface Bundle {
  slug: string;
  name: string;
  tagline: string;
  ideal_for: string;
  lines: BundleLine[];
  proposed_price_usd: { monthly: number } | { range_monthly: [number, number] };
  discount_note: string;
  cta_label: string;
  cta_href: string;
}

// `resolveLine`, `sumMonthlyUsd`, `fmtUsd`, `computeSavings` now live in
// `./helpers` (imported at the top of this file). Extracted so vitest can
// exercise the math without rendering the server component.

const BUNDLES: Bundle[] = [
  {
    slug: 'founder',
    name: 'Founder',
    tagline: 'Wealth-track + problem-intel + legal alerts for the solo operator.',
    ideal_for: 'Solo founders and fractional advisors who want the MADFAM base without enterprise lift.',
    lines: [
      { product_slug: 'dhanam', tier_slug: 'essentials' },
      { product_slug: 'fortuna', tier_slug: 'pro' },
      { product_slug: 'tezca', tier_slug: 'pro' },
    ],
    proposed_price_usd: { monthly: 4499 }, // $44.99 USD — ~20% off à-la-carte
    discount_note: 'Approximately 20% off à-la-carte list pricing.',
    cta_label: 'Join the waitlist',
    cta_href: 'mailto:bundles@madfam.io?subject=Founder%20bundle%20waitlist',
  },
  {
    slug: 'operator',
    name: 'Operator',
    tagline: 'Mid-market stack — personal + product + fabrication + legal.',
    ideal_for: 'Ops teams at Mexican scale-ups running the full MADFAM toolchain.',
    lines: [
      { product_slug: 'dhanam', tier_slug: 'pro' },
      { product_slug: 'fortuna', tier_slug: 'team' },
      { product_slug: 'forgesight', tier_slug: 'pro' },
      { product_slug: 'tezca', tier_slug: 'pro_plus' },
    ],
    proposed_price_usd: { monthly: 19900 }, // $199 USD — ~20% off à-la-carte
    discount_note: 'Approximately 20% off à-la-carte list pricing.',
    cta_label: 'Talk to sales',
    cta_href: 'mailto:bundles@madfam.io?subject=Operator%20bundle',
  },
  {
    slug: 'flywheel',
    name: 'Flywheel Suite',
    tagline: 'The whole ecosystem — orchestrated, compliant, connected.',
    ideal_for:
      'Enterprises adopting the full MADFAM Factory-as-a-Product protocol. SSO, SLA, dedicated success manager.',
    lines: [
      { product_slug: 'dhanam', tier_slug: 'premium' },
      { product_slug: 'selva', tier_slug: 'business' },
      { product_slug: 'forgesight', tier_slug: 'team' },
      { product_slug: 'fortuna', tier_slug: 'business' },
      {
        product_slug: 'tezca',
        tier_slug: 'enterprise',
        fallback_label: 'Enterprise (quote)',
      },
      { product_slug: 'karafiel', tier_slug: 'consultor' },
      { product_slug: 'routecraft', tier_slug: 'professional' },
    ],
    proposed_price_usd: { range_monthly: [149900, 199900] }, // $1,499-$1,999 USD
    discount_note:
      '20-30% off à-la-carte, structured as a quoted annual agreement. Enterprise tiers priced individually.',
    cta_label: 'Request a proposal',
    cta_href: 'mailto:bundles@madfam.io?subject=Flywheel%20Suite%20proposal',
  },
];

// --- Catalog resolution ------------------------------------------------------

async function fetchCatalog(): Promise<CatalogResponse | null> {
  const base =
    process.env.DHANAM_API_URL ??
    process.env.NEXT_PUBLIC_DHANAM_API_URL ??
    'https://api.dhan.am';
  const url = `${base.replace(/\/$/, '')}/v1/billing/catalog`;
  try {
    const res = await fetch(url, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return (await res.json()) as CatalogResponse;
  } catch {
    return null;
  }
}

// --- Rendering ---------------------------------------------------------------

function BundleCard({
  bundle,
  catalog,
}: {
  bundle: Bundle;
  catalog: CatalogResponse | null;
}) {
  const resolved = bundle.lines.map((l) => resolveLine(l, catalog));
  const alaCarteCents = sumMonthlyUsd(resolved);

  const bundleCents =
    'monthly' in bundle.proposed_price_usd
      ? bundle.proposed_price_usd.monthly
      : null;
  const bundleRange =
    'range_monthly' in bundle.proposed_price_usd
      ? bundle.proposed_price_usd.range_monthly
      : null;

  const savings = bundleCents
    ? alaCarteCents - bundleCents
    : bundleRange
      ? alaCarteCents - bundleRange[1]
      : 0;
  const savingsPct =
    alaCarteCents > 0 && savings > 0 ? (savings / alaCarteCents) * 100 : 0;

  return (
    <article className="pixel-border-accent rounded-sm bg-slate-900/60 p-6">
      <header className="mb-4">
        <h3 className="pixel-text mb-2 text-sm text-emerald-400">{bundle.name}</h3>
        <p className="text-sm leading-relaxed text-slate-300">{bundle.tagline}</p>
      </header>

      <p className="mb-5 text-xs italic leading-relaxed text-slate-500">
        {bundle.ideal_for}
      </p>

      <div className="mb-5 rounded-sm bg-slate-950/50 p-4">
        <div className="mb-1 text-[11px] uppercase tracking-wider text-slate-500">
          Proposed bundle price
        </div>
        <div className="text-xl text-emerald-300">
          {bundleCents
            ? `${fmtUsd(bundleCents)} /mo`
            : bundleRange
              ? `${fmtUsd(bundleRange[0])}–${fmtUsd(bundleRange[1])} /mo`
              : 'Quote'}
        </div>
        {alaCarteCents > 0 && savingsPct > 0 ? (
          <div className="mt-2 text-[11px] text-slate-400">
            <span className="line-through">{fmtUsd(alaCarteCents)}</span> à la carte ·
            <span className="ml-1 text-emerald-300">
              save ~{Math.round(savingsPct)}%
            </span>
          </div>
        ) : null}
        <p className="mt-2 text-[11px] text-slate-500">{bundle.discount_note}</p>
      </div>

      <h4 className="pixel-text mb-2 text-[11px] uppercase tracking-wider text-slate-500">
        Included
      </h4>
      <ul className="mb-5 space-y-1.5 text-xs text-slate-300">
        {resolved.map((r, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3">
            <span>
              <span className="text-slate-400">{r.product?.name ?? bundle.lines[i].product_slug}</span>
              <span className="ml-1 text-slate-500">· {r.tier_label}</span>
            </span>
            <span className="shrink-0 text-[11px] text-slate-500">
              {r.monthly_usd
                ? `${fmtUsd(r.monthly_usd)}/mo`
                : 'quote'}
            </span>
          </li>
        ))}
      </ul>

      <a
        href={bundle.cta_href}
        className="pixel-border-accent inline-flex items-center gap-2 rounded-sm bg-emerald-600/15 px-4 py-2 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-600/25"
      >
        {bundle.cta_label} →
      </a>
    </article>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-xl rounded-sm border border-rose-500/40 bg-rose-900/10 p-8 text-center">
      <h2 className="pixel-text mb-3 text-sm text-rose-300">Catalog unreachable</h2>
      <p className="text-sm leading-relaxed text-slate-400">
        Couldn&apos;t fetch the Dhanam billing catalog. À-la-carte totals
        below are proposals from the 2026-04-17 pricing overhaul, not
        live numbers.
      </p>
    </div>
  );
}

/**
 * Server-side admin gate. Reads the `janua-session` cookie JWT (already
 * verified by middleware before reaching here — we just decode the
 * payload to read `roles`), and redirects non-admins to /office.
 *
 * Kept inline rather than extracted to a shared util because (a) it's
 * the only admin-gated page in the app right now, and (b) the
 * "extracted util" rewrite lives with the eventual Janua middleware
 * refactor, not here.
 */
async function requireAdmin(): Promise<void> {
  const token = (await cookies()).get('janua-session')?.value;
  if (!token) redirect('/login?next=/bundles');

  try {
    const payload = token.split('.')[1];
    if (!payload) throw new Error('malformed JWT');
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(Buffer.from(padded, 'base64').toString('utf-8')) as {
      roles?: string[];
    };
    if (!claims.roles?.includes('admin')) redirect('/office');
  } catch {
    redirect('/login?next=/bundles');
  }
}

export default async function BundlesPage() {
  await requireAdmin();

  const catalog = await fetchCatalog();

  return (
    <div className="min-h-screen bg-slate-950 scanline-overlay">
      <main className="mx-auto max-w-6xl px-4 py-16">
        <div className="mb-10">
          <div className="mb-3 flex items-center gap-3 text-xs text-slate-500">
            <Link href="/" className="hover:text-emerald-400">
              ← selva.town
            </Link>
            <span>/</span>
            <span className="text-slate-400">bundles</span>
            <span className="ml-auto flex gap-3">
              <Link href="/atrium" className="text-slate-500 hover:text-emerald-400">
                Atrium →
              </Link>
              <Link href="/catalog" className="text-slate-500 hover:text-emerald-400">
                catalog →
              </Link>
              <Link href="/status" className="text-slate-500 hover:text-emerald-400">
                status →
              </Link>
            </span>
          </div>
          <h1 className="pixel-text mb-3 text-lg text-emerald-400">
            Ecosystem bundles
          </h1>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            Three curated MADFAM ecosystem bundles — the Founder indie
            pack, the Operator mid-market stack, and the Flywheel Suite
            enterprise package. Bundle pricing is proposed; individual
            SKUs are already in the Dhanam catalog. À-la-carte totals
            compute live from the catalog on every page load.
          </p>
        </div>

        {!catalog ? <EmptyState /> : null}

        <div className="grid gap-6 lg:grid-cols-3">
          {BUNDLES.map((b) => (
            <BundleCard key={b.slug} bundle={b} catalog={catalog} />
          ))}
        </div>

        <section className="mt-16 rounded-sm border border-amber-500/30 bg-amber-900/10 p-6">
          <h2 className="pixel-text mb-2 text-sm text-amber-300">
            Bundle SKUs not yet materialised in Stripe
          </h2>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            Stripe has no native bundle primitive. These three bundles
            are a marketing surface today; the purchase flow routes to
            sales. Modelling bundles as Stripe products (parent + child
            price references) is tracked as a follow-on to the 2026-04-17
            pricing overhaul — see the doc at{' '}
            <code>PRICING_OVERHAUL_20260417.md</code> section 4 for the
            rationale and the integration guard-rail ("no SKU in any
            bundle drops below its standalone LATAM-regional 45%-off
            net price").
          </p>
        </section>

        <div className="mt-12 text-center text-[11px] text-slate-600">
          Page revalidates every 5 minutes. À-la-carte math pulls live from{' '}
          <code>/v1/billing/catalog</code>.
        </div>
      </main>
    </div>
  );
}
