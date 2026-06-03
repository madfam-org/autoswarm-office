'use client';

import { Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useCallback } from 'react';

const isDev = process.env.NODE_ENV === 'development' || process.env.NODE_ENV === 'test';

const DUMMY_JWT_PAYLOAD =
  'eyJzdWIiOiJkZXYtdXNlciIsInJvbGVzIjpbImFkbWluIiwidGFjdGljaWFuIl0sIm9yZ19pZCI6ImRldi1vcmciLCJlbWFpbCI6ImRldkBhdXRvc3dhcm0ubG9jYWwifQ==';
const DUMMY_JWT = `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.${DUMMY_JWT_PAYLOAD}.`;

function ShieldIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function SSOButton({ redirect }: { redirect: string }) {
  const ssoUrl = `/api/auth/sso?redirect=${encodeURIComponent(redirect)}`;

  return (
    <a
      href={ssoUrl}
      className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900"
      role="button"
    >
      <ShieldIcon className="h-4 w-4" />
      Enterprise SSO
    </a>
  );
}

function SocialLoginButton({
  provider,
  icon,
  redirect,
}: {
  provider: string;
  icon: React.ReactNode;
  redirect: string;
}) {
  const ssoUrl = `/api/auth/sso?redirect=${encodeURIComponent(redirect)}&provider=${provider}`;

  return (
    <a
      href={ssoUrl}
      className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700 hover:text-white focus:outline-none focus:ring-2 focus:ring-gray-600 focus:ring-offset-2 focus:ring-offset-gray-900"
      role="button"
    >
      {icon}
      {provider}
    </a>
  );
}

function GoogleIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
      />
      <path
        fill="currentColor"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="currentColor"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
      />
      <path
        fill="currentColor"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2z" />
    </svg>
  );
}

function LoginForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const redirect = searchParams.get('redirect') ?? '/';

  const handleDevLogin = useCallback(() => {
    document.cookie = `janua-session=${DUMMY_JWT}; path=/; max-age=86400; SameSite=Lax`;
    router.push(redirect);
  }, [redirect, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-900 p-8 shadow-xl">
        {/* Header */}
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold tracking-tight text-white">Selva Admin</h1>
          <p className="mt-1 text-sm text-gray-400">Sign in to access the admin console</p>
        </div>

        {/* Enterprise SSO button */}
        <SSOButton redirect={redirect} />

        {/* Divider */}
        <div className="relative my-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-800" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-gray-900 px-2 text-gray-500">or continue with</span>
          </div>
        </div>

        {/* Social login options */}
        <div className="flex gap-3">
          <SocialLoginButton
            provider="Google"
            icon={<GoogleIcon />}
            redirect={redirect}
          />
          <SocialLoginButton
            provider="GitHub"
            icon={<GitHubIcon />}
            redirect={redirect}
          />
        </div>

        {/* Dev-only login button */}
        {isDev && (
          <>
            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-amber-900/40" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-gray-900 px-2 text-amber-500">development only</span>
              </div>
            </div>

            <button
              type="button"
              onClick={handleDevLogin}
              className="w-full rounded-lg border border-amber-900/40 bg-amber-600/10 px-4 py-2.5 text-sm font-medium text-amber-400 transition-colors hover:bg-amber-600/20 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 focus:ring-offset-gray-900"
            >
              Login as Dev User
            </button>
          </>
        )}

        {/* Legal links */}
        <p className="mt-6 text-center text-xs text-gray-500">
          By signing in, you agree to the{' '}
          <a
            href="https://selva.town/terms"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-400 underline hover:text-gray-300"
          >
            Terms of Service
          </a>{' '}
          and{' '}
          <a
            href="https://selva.town/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-400 underline hover:text-gray-300"
          >
            Privacy Policy
          </a>
        </p>

        {/* Powered by Janua footer */}
        <div className="mt-4 flex items-center justify-center gap-1.5 text-xs text-gray-600">
          <ShieldIcon className="h-3 w-3" />
          <span>Powered by Janua</span>
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
