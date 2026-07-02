import { NextRequest, NextResponse } from 'next/server';

/**
 * SSO Initiation Route
 *
 * Generates PKCE parameters, stores state/verifier in httpOnly cookies,
 * and redirects to the Janua authorization endpoint.
 */

const JANUA_BASE_URL =
  process.env.NEXT_PUBLIC_JANUA_BASE_URL ||
  process.env.NEXT_PUBLIC_JANUA_ISSUER_URL ||
  'https://auth.madfam.io';

const CLIENT_ID =
  process.env.JANUA_CLIENT_ID ||
  process.env.NEXT_PUBLIC_JANUA_CLIENT_ID ||
  process.env.NEXT_PUBLIC_JANUA_PUBLISHABLE_KEY ||
  'selva-office';

function getCallbackUrl(request: NextRequest): string {
  const proto = request.headers.get('x-forwarded-proto') || 'http';
  const host = request.headers.get('x-forwarded-host') || request.headers.get('host') || 'localhost:4302';
  return `${proto}://${host}/api/auth/callback`;
}

/**
 * Generate a cryptographically random string for PKCE and state parameters.
 */
function generateRandomString(length: number): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (byte) => byte.toString(36).padStart(2, '0'))
    .join('')
    .slice(0, length);
}

/**
 * Generate PKCE code challenge from verifier using SHA-256.
 */
async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const redirect = searchParams.get('redirect') || '/';
  const provider = searchParams.get('provider'); // Optional: google, github

  const state = generateRandomString(32);
  const codeVerifier = generateRandomString(64);
  const codeChallenge = await generateCodeChallenge(codeVerifier);

  const callbackUrl = getCallbackUrl(request);

  // Build the authorization URL
  const authUrl = new URL('/api/v1/oauth/authorize', JANUA_BASE_URL);
  authUrl.searchParams.set('response_type', 'code');
  authUrl.searchParams.set('client_id', CLIENT_ID);
  authUrl.searchParams.set('redirect_uri', callbackUrl);
  authUrl.searchParams.set('scope', 'openid profile email roles');
  authUrl.searchParams.set('state', state);
  authUrl.searchParams.set('code_challenge', codeChallenge);
  authUrl.searchParams.set('code_challenge_method', 'S256');

  // If a social provider was requested, hint at it
  if (provider) {
    authUrl.searchParams.set('connection', provider);
  }

  const response = NextResponse.redirect(authUrl.toString());

  // Store PKCE verifier and state in httpOnly cookies with 5-minute TTL
  const cookieOptions = {
    path: '/',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax' as const,
    maxAge: 300, // 5 minutes
  };

  response.cookies.set('oauth_state', state, cookieOptions);
  response.cookies.set('oauth_code_verifier', codeVerifier, cookieOptions);
  response.cookies.set('oauth_redirect', redirect, {
    ...cookieOptions,
    maxAge: 600, // 10 minutes to account for slow auth flows
  });

  return response;
}
