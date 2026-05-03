import { getSiteConfig } from '@/lib/site-config';

export function HeroSection() {
  const { appUrl } = getSiteConfig();
  return (
    <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-4 text-center">
      {/* Animated background grid — solarpunk green */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        aria-hidden="true"
        style={{
          backgroundImage:
            'linear-gradient(rgba(74,158,110,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(74,158,110,0.5) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
        }}
      />

      {/* Floating particle dots */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="landing-particle" style={{ left: '10%', top: '20%', animationDelay: '0s', animationDuration: '6s' }} />
        <div className="landing-particle" style={{ left: '25%', top: '70%', animationDelay: '1.2s', animationDuration: '7s' }} />
        <div className="landing-particle" style={{ left: '45%', top: '15%', animationDelay: '2.4s', animationDuration: '5.5s' }} />
        <div className="landing-particle" style={{ left: '60%', top: '80%', animationDelay: '0.8s', animationDuration: '6.5s' }} />
        <div className="landing-particle" style={{ left: '75%', top: '35%', animationDelay: '3.2s', animationDuration: '7.5s' }} />
        <div className="landing-particle" style={{ left: '90%', top: '55%', animationDelay: '1.6s', animationDuration: '5s' }} />
        <div className="landing-particle" style={{ left: '35%', top: '45%', animationDelay: '4s', animationDuration: '6.8s' }} />
        <div className="landing-particle" style={{ left: '80%', top: '10%', animationDelay: '2s', animationDuration: '5.8s' }} />
      </div>

      {/* Live badge */}
      <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-800/40 bg-emerald-950/40 px-4 py-1.5 text-xs text-emerald-400">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
        Live &mdash; 10 agents online
      </div>

      {/* Brand */}
      <h1 className="pixel-text animate-glow-pulse mb-4 bg-gradient-to-r from-emerald-400 via-amber-300 to-emerald-400 bg-clip-text text-3xl leading-relaxed text-transparent sm:text-5xl md:text-6xl">
        Selva
      </h1>

      {/* Tagline */}
      <p className="mb-3 max-w-2xl text-lg font-light leading-relaxed text-slate-200 sm:text-xl md:text-2xl">
        Your AI workforce, alive in a virtual office.
      </p>

      {/* Value proposition */}
      <p className="mb-8 max-w-xl text-sm leading-relaxed text-slate-400 sm:text-base">
        Walk into a solarpunk office where 10 AI agents code, research, file
        taxes, and deploy software &mdash; all in real time, all under your
        control. Every action requires your approval. No black boxes.
      </p>

      {/* Metrics */}
      <div className="mb-10 grid grid-cols-2 gap-4 sm:flex sm:flex-wrap sm:items-center sm:justify-center sm:gap-x-6 sm:gap-y-2">
        <div className="flex flex-col items-center">
          <span className="text-2xl font-bold text-emerald-400 sm:text-3xl">10</span>
          <span className="text-xs text-slate-500">Named Agents</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-2xl font-bold text-amber-400 sm:text-3xl">54</span>
          <span className="text-xs text-slate-500">Built-in Tools</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-2xl font-bold text-cyan-400 sm:text-3xl">6</span>
          <span className="text-xs text-slate-500">Graph Types</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-2xl font-bold text-purple-400 sm:text-3xl">100%</span>
          <span className="text-xs text-slate-500">Human-in-the-Loop</span>
        </div>
      </div>

      {/* CTAs */}
      <div className="flex flex-wrap items-center justify-center gap-4">
        <a
          href={`${appUrl}/demo`}
          className="retro-btn pixel-border-accent group relative rounded bg-gradient-to-r from-emerald-600 to-emerald-500 px-10 py-4 text-sm font-semibold text-white shadow-lg shadow-emerald-900/30 transition-all hover:from-emerald-500 hover:to-emerald-400 hover:shadow-emerald-800/40"
        >
          Try the Live Demo
          <span className="ml-2 inline-block transition-transform group-hover:translate-x-1">&rarr;</span>
        </a>
        <a
          href={appUrl}
          className="retro-btn rounded border border-slate-600 px-10 py-4 text-sm font-medium text-slate-300 transition-colors hover:border-emerald-500 hover:text-white"
        >
          Sign In
        </a>
      </div>

      <p className="mt-6 text-xs text-slate-600">
        No account needed for the demo. Walk in, dispatch a task, watch it happen.
      </p>

      {/* Scroll indicator */}
      <div className="absolute bottom-8 flex flex-col items-center gap-2 text-slate-600">
        <span className="text-xs">Scroll to explore</span>
        <div className="h-6 w-px animate-pulse bg-gradient-to-b from-slate-600 to-transparent" />
      </div>
    </section>
  );
}
