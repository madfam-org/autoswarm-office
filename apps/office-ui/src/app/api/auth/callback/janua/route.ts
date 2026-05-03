import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { logger } from '@/lib/logger';

const JANUA_ISSUER = process.env.NEXT_PUBLIC_JANUA_ISSUER_URL || 'https://auth.madfam.io';
const CLIENT_ID = process.env.NEXT_PUBLIC_JANUA_CLIENT_ID || 'autoswarm-office';

function getOrigin(request: Request): string {
  const h = new Headers(request.headers);
  const host = h.get('x-forwarded-host') || h.get('host') || new URL(request.url).host;
  const proto = h.get('x-forwarded-proto') || 'https';
  return `${proto}://${host}`;
}

/**
 * GET /api/auth/callback/janua
 *
 * OAuth 2.0 Authorization Code callback with PKCE (public client).
 * 1. Exchanges the authorization code for an access token
 * 2. Stores the access token as a session cookie
 * 3. Redirects to the office
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const origin = getOrigin(request);
  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state') || '/office';
  const error = url.searchParams.get('error');

  if (error) {
    const desc = url.searchParams.get('error_description') || error;
    return NextResponse.redirect(`${origin}/login?sso_error=${encodeURIComponent(desc)}`);
  }

  if (!code) {
    return NextResponse.redirect(`${origin}/login?sso_error=${encodeURIComponent('Missing authorization code')}`);
  }

  // Retrieve PKCE verifier from cookie
  const cookieStore = await cookies();
  const codeVerifier = cookieStore.get('janua-pkce-verifier')?.value;

  // Exchange code for tokens
  const redirectUri = `${origin}/api/auth/callback/janua`;
  const tokenParams = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
    client_id: CLIENT_ID,
    ...(codeVerifier ? { code_verifier: codeVerifier } : {}),
  });

  let tokenData: { access_token: string; expires_in?: number };

  try {
    const tokenRes = await fetch(`${JANUA_ISSUER}/api/v1/oauth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: tokenParams,
    });

    if (!tokenRes.ok) {
      const body = await tokenRes.text();
      logger.error('Token exchange failed:', tokenRes.status, body);
      return NextResponse.redirect(`${origin}/login?sso_error=${encodeURIComponent('Token exchange failed')}`);
    }

    tokenData = await tokenRes.json();
  } catch (err) {
    logger.error('Token exchange error:', err);
    return NextResponse.redirect(`${origin}/login?sso_error=${encodeURIComponent('Auth server unreachable')}`);
  }

  // Clean up PKCE cookies
  cookieStore.delete('janua-pkce-verifier');
  cookieStore.delete('janua-oauth-state');

  // Set the access token as the session cookie
  // The office-ui middleware checks this cookie for protected routes
  const expiresIn = tokenData.expires_in || 86400;
  cookieStore.set('janua-session', tokenData.access_token, {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: expiresIn,
  });

  // Also set a short-lived non-httpOnly cookie for client-side hydration
  cookieStore.set('janua-sso-tokens', JSON.stringify({
    access_token: tokenData.access_token,
    expires_at: Math.floor(Date.now() / 1000 + expiresIn),
  }), {
    httpOnly: false,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 60, // 60 seconds — client reads and deletes
  });

  return NextResponse.redirect(`${origin}${state}`);
}
