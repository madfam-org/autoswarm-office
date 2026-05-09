const SERVICES = [
  { name: 'Tezca', desc: 'Legal Intelligence', url: 'https://tezca.mx', emoji: '\u2696\uFE0F' },
  { name: 'Dhanam', desc: 'Financial Platform', url: 'https://dhan.am', emoji: '\uD83D\uDCB0' },
  { name: 'Fortuna', desc: 'Problem Intelligence', url: 'https://fortuna.tube', emoji: '\uD83D\uDD0D' },
  { name: 'Yantra4D', desc: '3D Design Platform', url: 'https://yantra4d.com', emoji: '\uD83C\uDFA8' },
  { name: 'Enclii', desc: 'DevOps Platform', url: 'https://enclii.dev', emoji: '\uD83D\uDE80' },
  { name: 'Cotiza Studio', desc: 'Fabrication Quoting', url: 'https://cotiza.studio', emoji: '\uD83C\uDFED' },
  { name: 'PhyndCRM', desc: 'Phygital CRM', url: 'https://crm.madfam.io', emoji: '\uD83D\uDCCA' },
  { name: 'CEQ', desc: 'Creative AI Engine', url: 'https://ceq.lol', emoji: '\uD83C\uDFAC' },
];

export function EcosystemLinks() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-24">
      <h2 className="pixel-text mb-4 text-center text-lg text-emerald-400">
        Part of the MADFAM Ecosystem
      </h2>

      <p className="mb-14 text-center text-sm text-slate-500">
        Selva powers the AI backbone for an entire product ecosystem.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {SERVICES.map((service) => (
          <a
            key={service.name}
            href={service.url}
            target="_blank"
            rel="noopener noreferrer"
            className="retro-panel group flex items-center gap-4 rounded-lg p-4 transition-transform hover:-translate-y-0.5"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-700/50 text-xl" aria-hidden="true">
              {service.emoji}
            </span>
            <div className="min-w-0">
              <h3 className="pixel-text text-[9px] leading-relaxed text-white group-hover:text-indigo-300">
                {service.name}
              </h3>
              <p className="truncate text-xs text-slate-500">
                {service.desc}
              </p>
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
