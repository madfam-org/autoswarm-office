/**
 * selva.town/catalog — unified MADFAM ecosystem offer view.
 *
 * Fetches from Dhanam's public ``/v1/billing/catalog`` (same endpoint every
 * ecosystem pricing page hits) and renders every priced product, tier,
 * price (MXN + USD), and feature in one place. Un-monetized products
 * live in a separate section so operators can see exactly what's for sale
 * today and what still needs a pricing decision.
 *
 * Single source of truth lives in ``dhanam/catalog.yaml``; this page just
 * visualises it. No pricing is baked in here — changing the page requires
 * a Dhanam catalog sync, not a Selva redeploy.
 */
import type { Metadata } from 'next';
import Link from 'next/link';

// Revalidate every 5 minutes — matches the Dhanam catalog cache TTL.
export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Selva — MADFAM Offer Catalog',
  description:
    'Live view of every MADFAM product, pricing tier, and credit cost across the ecosystem. Sourced from Dhanam.',
};

// Mirror of Dhanam's `CatalogProduct` shape (apps/api/src/modules/billing/
// services/product-catalog.service.ts). We re-state it here rather than
// sharing types cross-repo.
interface CatalogPrice {
  monthly: number | null;
  yearly: number | null;
}
interface CatalogTier {
  tierSlug: string;
  dhanamTier: string;
  displayName: string | null;
  description: string | null;
  metadata: Record<string, unknown> | null;
  prices: Record<string, CatalogPrice>;
  features: string[];
}
interface CatalogCreditCost {
  operation: string;
  credits: number;
  label: string | null;
}
interface CatalogProduct {
  slug: string;
  name: string;
  description: string | null;
  category: string;
  iconUrl: string | null;
  websiteUrl: string | null;
  tiers: CatalogTier[];
  creditCosts: CatalogCreditCost[];
}

// Products that exist in prod (deployed) but aren't yet priced / synced
// to Stripe. Lifted from the 2026-04-17 catalog audit. Kept inline because
// "we don't sell this yet" is a pricing decision, not a code constant —
// when a price is committed, the product moves into dhanam/catalog.yaml
// and this array shrinks on the next deploy.
const UNPRICED_PRODUCTS: {
  slug: string;
  name: string;
  description: string;
  status: 'prototype' | 'live' | 'staging';
  reason: string;
}[] = [
  {
    slug: 'rondelio',
    name: 'Rondelio',
    description: 'Game Intelligence Cloud.',
    status: 'staging',
    reason: 'No pricing committed. DB provisioned; catalog entry pending SKU decision.',
  },
  {
    slug: 'sim4d',
    name: 'Sim4D',
    description: 'Parametric CAD (previously BrepFlow). Live web, no billing.',
    status: 'live',
    reason: 'No pricing committed.',
  },
  {
    slug: 'zavlo',
    name: 'Zavlo',
    description: 'Admin surface for MADFAM-internal operations.',
    status: 'prototype',
    reason: 'Internal tool — unlikely to monetize externally.',
  },
  {
    slug: 'forj',
    name: 'Forj',
    description: '3D digital asset mint + checkout.',
    status: 'staging',
    reason: 'Pricing blocked on mint/checkout flow completion.',
  },
  {
    slug: 'pravara-mes',
    name: 'Pravara MES',
    description: 'Manufacturing execution system — physical bridge to FaaP.',
    status: 'staging',
    reason: 'No pricing committed. Phygital supply-chain partner selection pending.',
  },
];

interface CatalogResponse {
  products: CatalogProduct[];
  updatedAt: string;
}

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

function formatMoney(amountCents: number, currency: string): string {
  const major = amountCents / 100;
  const locale = currency === 'MXN' ? 'es-MX' : 'en-US';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(major);
}

function categoryChip(cat: string) {
  const map: Record<string, string> = {
    finance: 'bg-emerald-600/20 text-emerald-300',
    compliance: 'bg-amber-600/20 text-amber-300',
    infrastructure: 'bg-indigo-600/20 text-indigo-300',
    legal: 'bg-rose-600/20 text-rose-300',
    fabrication: 'bg-purple-600/20 text-purple-300',
    intelligence: 'bg-cyan-600/20 text-cyan-300',
  };
  const cls =
    map[cat] ?? 'bg-slate-600/30 text-slate-300';
  return (
    <span
      className={`inline-flex items-center rounded-sm px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cls}`}
    >
      {cat}
    </span>
  );
}

function TierCard({ tier }: { tier: CatalogTier }) {
  const currencies = Object.keys(tier.prices);
  const hasPrice = currencies.some(
    (c) => tier.prices[c]?.monthly || tier.prices[c]?.yearly,
  );
  return (
    <div className="pixel-border-accent rounded-sm bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="pixel-text text-xs text-white">
          {tier.displayName ?? tier.tierSlug}
        </h4>
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          {tier.dhanamTier}
        </span>
      </div>
      {hasPrice ? (
        <div className="mb-3 space-y-1 text-sm">
          {currencies.map((c) => {
            const p = tier.prices[c];
            if (!p?.monthly && !p?.yearly) return null;
            return (
              <div key={c} className="flex items-baseline gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {c}
                </span>
                {p.monthly ? (
                  <span className="text-emerald-300">
                    {formatMoney(p.monthly, c)}
                    <span className="text-[11px] text-slate-500"> /mo</span>
                  </span>
                ) : null}
                {p.yearly ? (
                  <span className="text-[11px] text-slate-400">
                    · {formatMoney(p.yearly, c)}
                    <span className="text-slate-500"> /yr</span>
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mb-3 text-[11px] italic text-amber-300">
          Sales-driven (custom pricing, no Stripe price)
        </div>
      )}
      {tier.features.length > 0 ? (
        <ul className="space-y-1 text-[11px] text-slate-400">
          {tier.features.slice(0, 6).map((f, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-emerald-400">✓</span>
              <span className="leading-snug">{f}</span>
            </li>
          ))}
          {tier.features.length > 6 ? (
            <li className="pt-1 text-[11px] text-slate-500">
              +{tier.features.length - 6} more
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

function ProductBlock({ product }: { product: CatalogProduct }) {
  return (
    <article className="mb-10">
      <header className="mb-4 flex flex-wrap items-baseline gap-3">
        <h3 className="pixel-text text-sm text-emerald-400">{product.name}</h3>
        {categoryChip(product.category)}
        {product.websiteUrl ? (
          <a
            href={product.websiteUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-slate-400 hover:text-emerald-400"
          >
            {product.websiteUrl.replace(/^https?:\/\//, '')} ↗
          </a>
        ) : null}
      </header>
      {product.description ? (
        <p className="mb-5 max-w-3xl text-sm leading-relaxed text-slate-400">
          {product.description}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {product.tiers.map((t) => (
          <TierCard key={t.tierSlug} tier={t} />
        ))}
      </div>
      {product.creditCosts.length > 0 ? (
        <div className="mt-4">
          <h4 className="pixel-text mb-2 text-[11px] uppercase tracking-wider text-slate-500">
            Credit costs
          </h4>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-400 md:grid-cols-4">
            {product.creditCosts.map((c) => (
              <div
                key={c.operation}
                className="flex items-baseline justify-between gap-2"
              >
                <dt className="truncate text-slate-500">{c.operation}</dt>
                <dd className="text-slate-300">{c.credits}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </article>
  );
}

function UnpricedSection() {
  return (
    <section className="mt-16 rounded-sm border border-amber-500/30 bg-amber-900/10 p-6">
      <h2 className="pixel-text mb-2 text-sm text-amber-300">
        Deployed but not yet priced
      </h2>
      <p className="mb-5 max-w-3xl text-sm leading-relaxed text-slate-400">
        These products are deployed or staged in production infrastructure
        but have no committed pricing in the Dhanam catalog, so they have
        no Stripe products and cannot be sold today. They are visible here
        so the gap is hard to ignore — every row is a committed-to-pricing
        decision away from being a revenue stream.
      </p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {UNPRICED_PRODUCTS.map((p) => (
          <li
            key={p.slug}
            className="rounded-sm border border-amber-500/20 bg-slate-900/50 p-4"
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="pixel-text text-xs text-white">{p.name}</h3>
              <span className="rounded-sm bg-amber-600/20 px-2 py-0.5 text-[10px] uppercase tracking-wider text-amber-300">
                {p.status}
              </span>
            </div>
            <p className="mb-2 text-xs leading-relaxed text-slate-400">
              {p.description}
            </p>
            <p className="text-[11px] italic text-amber-200/80">{p.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-xl rounded-sm border border-rose-500/40 bg-rose-900/10 p-8 text-center">
      <h2 className="pixel-text mb-3 text-sm text-rose-300">
        Catalog unreachable
      </h2>
      <p className="text-sm leading-relaxed text-slate-400">
        Couldn&apos;t fetch <code>/v1/billing/catalog</code> from Dhanam.
        The catalog is the single source of truth for every priced product
        in the ecosystem. If this page is empty, pricing pages across
        MADFAM are empty too.
      </p>
      <p className="mt-4 text-xs text-slate-500">
        Set <code>DHANAM_API_URL</code> in the office-ui environment (prod
        default is <code>https://api.dhan.am</code>).
      </p>
    </div>
  );
}

export default async function CatalogPage() {
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
            <span className="text-slate-400">catalog</span>
            <span className="ml-auto flex gap-3">
              <Link href="/atrium" className="text-slate-500 hover:text-emerald-400">
                Atrium →
              </Link>
              <Link href="/bundles" className="text-slate-500 hover:text-emerald-400">
                bundles →
              </Link>
              <Link href="/status" className="text-slate-500 hover:text-emerald-400">
                status →
              </Link>
            </span>
          </div>
          <h1 className="pixel-text mb-3 text-lg text-emerald-400">
            MADFAM offer catalog
          </h1>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            Live view of every priced product, pulled from Dhanam&rsquo;s
            public billing catalog. Any change here starts with an edit to{' '}
            <code>dhanam/catalog.yaml</code> + a run of{' '}
            <code>sync-catalog.ts</code>, which materialises Stripe
            products and the Dhanam plan DB atomically.
          </p>
          {catalog ? (
            <p className="mt-3 text-[11px] text-slate-500">
              {catalog.products.length} priced products · updated{' '}
              {new Date(catalog.updatedAt).toLocaleString('es-MX')}
            </p>
          ) : null}
        </div>

        {catalog && catalog.products.length > 0 ? (
          <div>
            {catalog.products.map((p) => (
              <ProductBlock key={p.slug} product={p} />
            ))}
          </div>
        ) : (
          <EmptyState />
        )}

        <UnpricedSection />

        <div className="mt-16 text-center text-[11px] text-slate-600">
          Page revalidates every 5 minutes · Dhanam catalog TTL matches
        </div>
      </main>
    </div>
  );
}
