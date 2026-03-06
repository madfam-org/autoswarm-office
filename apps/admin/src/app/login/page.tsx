'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { useCallback } from 'react';

const DUMMY_JWT_PAYLOAD =
  'eyJzdWIiOiJkZXYtdXNlciIsInJvbGVzIjpbImFkbWluIiwidGFjdGljaWFuIl0sIm9yZ19pZCI6ImRldi1vcmciLCJlbWFpbCI6ImRldkBhdXRvc3dhcm0ubG9jYWwifQ==';

/** Dev-only header + payload (no signature). Good enough for local work. */
const DUMMY_JWT = `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.${DUMMY_JWT_PAYLOAD}.`;

export default function LoginPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const handleLogin = useCallback(() => {
    const redirect = searchParams.get('redirect') ?? '/';
    document.cookie = `janua_session=${DUMMY_JWT}; path=/; max-age=86400; SameSite=Lax`;
    router.push(redirect);
  }, [searchParams, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-amber-900/40 bg-gray-900 p-8 shadow-xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold tracking-tight text-white">AutoSwarm Admin</h1>
          <p className="mt-1 text-sm text-amber-400/80">Admin Development Login</p>
        </div>

        <button
          type="button"
          onClick={handleLogin}
          className="w-full rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 focus:ring-offset-gray-900"
        >
          Login as Dev User
        </button>

        <p className="mt-6 text-center text-xs text-gray-500">
          This page will be replaced with Janua SSO in production
        </p>
      </div>
    </main>
  );
}
