/**
 * Static fallback used IF play.rondel.io is later locked down (CSP,
 * X-Frame-Options) and the iframe in the modal can't render. Right
 * now (2026-05-04) the headers are clean and the iframe loads, so
 * this page is dormant — but it exists so we never have to ship a
 * broken portal. The modal uses iframe-by-default with a "Open in
 * new tab" link as the inline fallback; this page is the absolute
 * last-ditch destination.
 */
import Link from 'next/link';

export const metadata = {
  title: 'Jumanji Portal — Coming Soon',
  robots: { index: false, follow: false },
};

export default function JumanjiComingSoon() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#0e1f15] p-8 text-emerald-200">
      <div className="max-w-lg space-y-6 rounded-md border border-emerald-700/60 bg-[#0a1810] p-8 shadow-[0_0_60px_rgba(95,196,138,0.25)]">
        <h1 className="pixel-text text-base text-emerald-300">
          The dice rolled. The path is being cleared.
        </h1>
        <p className="text-sm leading-relaxed text-emerald-100/80">
          The simulator at <code>play.rondel.io</code> is being readied. Step
          back into the office and try again shortly.
        </p>
        <Link
          href="/"
          className="inline-block rounded-sm border border-emerald-500 bg-emerald-700/30 px-4 py-2 text-xs uppercase tracking-wider text-emerald-200 hover:bg-emerald-700/50"
        >
          ← back to selva.town
        </Link>
      </div>
    </main>
  );
}
