'use client';

import { useEffect, useState, useCallback } from 'react';
import { OfficeExperience } from '@/components/OfficeExperience';
import { PreJoinScreen, shouldSkipPreJoin } from '@/components/PreJoinScreen';
import { ThemeToggle } from '@/components/ThemeToggle';

function generateDemoJWT(name: string): string {
  const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const randomId = Math.random().toString(36).substring(2, 10);
  const payload = btoa(
    JSON.stringify({
      sub: `demo-${randomId}`,
      roles: ['demo'],
      org_id: 'demo-public',
      email: 'demo@selva.town',
      name: name || 'Visitor',
    }),
  );
  return `${header}.${payload}.`;
}

export default function DemoPage() {
  const [entered, setEntered] = useState(false);
  const [preJoinDone, setPreJoinDone] = useState(false);
  const [name, setName] = useState('');

  const enterDemo = useCallback(() => {
    // Clear any existing session to avoid conflicts
    document.cookie = 'janua-session=; path=/; max-age=0';
    const jwt = generateDemoJWT(name);
    document.cookie = `janua-session=${jwt}; path=/; max-age=3600; SameSite=Lax`;
    setPreJoinDone(shouldSkipPreJoin());
    setEntered(true);
  }, [name]);

  // Auto-enter if a demo session already exists
  useEffect(() => {
    const match = document.cookie.match(/(?:^|;\s*)janua-session=([^;]*)/);
    if (match?.[1]) {
      try {
        const payload = JSON.parse(atob(match[1].split('.')[1]));
        if (payload.org_id === 'demo-public' && payload.roles?.includes('demo')) {
          setEntered(true);
          return;
        }
      } catch { /* not a demo token, continue to picker */ }
    }
  }, []);

  if (entered && !preJoinDone) {
    return (
      <PreJoinScreen
        spaceName="the Selva demo"
        defaultName={name || 'Visitor'}
        onJoin={() => setPreJoinDone(true)}
      />
    );
  }

  if (entered) {
    return <OfficeExperience mode="demo" />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface scanline-overlay">
      <div className="fixed left-4 top-4">
        <ThemeToggle />
      </div>
      <div className="retro-panel w-full max-w-sm animate-pop-in rounded p-8">
        <h1 className="pixel-text mb-2 text-center text-lg text-indigo-400">
          Try the Demo
        </h1>
        <p className="mb-6 text-center text-sm text-slate-400">
          Explore the office with simulated AI agents. No sign-up required.
        </p>

        <label htmlFor="demoName" className="mb-1 block text-xs text-slate-400">
          Display name (optional)
        </label>
        <input
          id="demoName"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Visitor"
          maxLength={30}
          autoFocus
          onKeyDown={(e) => { if (e.key === 'Enter') enterDemo(); }}
          className="mb-4 w-full rounded border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
        />

        <button
          onClick={enterDemo}
          className="retro-btn w-full rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500"
        >
          Enter Demo
        </button>

        <div className="mt-6 text-center">
          <a
            href="/login"
            className="text-xs text-slate-500 transition-colors hover:text-indigo-400"
          >
            Have an account? Sign in
          </a>
        </div>
      </div>
    </div>
  );
}
