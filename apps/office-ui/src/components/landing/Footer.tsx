import { getSiteConfig } from '@/lib/site-config';

const YEAR = new Date().getFullYear();

const ECOSYSTEM_LINKS = [
  { label: 'PhyneCRM', href: 'https://crm.madfam.io' },
  { label: 'Dhanam', href: 'https://dhan.am' },
  { label: 'Karafiel', href: 'https://karafiel.mx' },
];

export function Footer() {
  const { appUrl } = getSiteConfig();
  const links = [
    { label: 'Office App', href: appUrl },
    { label: 'Demo', href: `${appUrl}/demo` },
    { label: 'API Docs', href: `${appUrl}/api/v1/docs` },
    { label: 'GitHub', href: 'https://github.com/madfam-org' },
  ];
  return (
    <footer className="border-t border-slate-800/60 px-4 py-10">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-6 sm:flex-row">
        {/* Left: branding */}
        <div className="text-center sm:text-left">
          <span className="pixel-text text-[8px] text-emerald-400/60">
            Selva
          </span>
          <p className="mt-1 text-xs text-slate-600">
            &copy; {YEAR} Selva. By{' '}
            <a
              href="https://madfam.io"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-slate-400"
            >
              Innovaciones MADFAM
            </a>
            .
          </p>
        </div>

        {/* Center: nav links */}
        <nav aria-label="Footer navigation">
          <ul className="flex flex-wrap items-center justify-center gap-6">
            {links.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  target={link.href.startsWith('http') ? '_blank' : undefined}
                  rel={link.href.startsWith('http') ? 'noopener noreferrer' : undefined}
                  className="text-sm text-slate-500 transition-colors hover:text-indigo-400"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        {/* Right: status + legal */}
        <div className="flex flex-col items-center gap-3 sm:items-end">
          <a
            href="https://status.madfam.io"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-slate-700/60 px-3 py-1.5 text-xs text-slate-500 transition-colors hover:border-emerald-600/40 hover:text-emerald-400"
          >
            <span
              className="inline-block h-2 w-2 rounded-full bg-emerald-500"
              aria-hidden="true"
            />
            Status
          </a>
          <div className="flex items-center gap-3 text-xs text-slate-600">
            <a
              href="https://madfam.io/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-slate-400 transition-colors"
            >
              Privacy Policy
            </a>
            <span aria-hidden="true">&middot;</span>
            <a
              href="https://madfam.io/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-slate-400 transition-colors"
            >
              Terms of Service
            </a>
          </div>
        </div>
      </div>

      {/* Ecosystem links */}
      <div className="mx-auto mt-6 flex max-w-5xl items-center justify-center gap-4 border-t border-slate-800/40 pt-6">
        <span className="text-xs text-slate-600">Ecosystem:</span>
        {ECOSYSTEM_LINKS.map((link) => (
          <a
            key={link.label}
            href={link.href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-slate-500 transition-colors hover:text-indigo-400"
          >
            {link.label}
          </a>
        ))}
      </div>
    </footer>
  );
}
