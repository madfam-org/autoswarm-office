import { NextRequest, NextResponse } from 'next/server';
import { SignJWT } from 'jose';
import { logger } from '@/lib/logger';

/**
 * OAuth Callback Route
 *
 * Handles the authorization code callback from Janua:
 * 1. Validates state parameter against stored cookie
 * 2. Exchanges authorization code for tokens via PKCE
 * 3. Fetches user info from Janua
 * 4. Creates a signed session cookie (HS256 via jose)
 * 5. Redirects to the original destination
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

const SESSION_SECRET = process.env.JANUA_SECRET_KEY || process.env.SESSION_SECRET || '';

function getCallbackUrl(request: NextRequest): string {
  const proto = request.headers.get('x-forwarded-proto') || 'http';
  const host = request.headers.get('x-forwarded-host') || request.headers.get('host') || 'localhost:4302';
  return `${proto}://${host}/api/auth/callback`;
}

function errorRedirect(request: NextRequest, message: string): NextResponse {
  const loginUrl = new URL('/login', request.url);
  loginUrl.searchParams.set('error', message);
  const response = NextResponse.redirect(loginUrl.toString());

  // Clear OAuth cookies on error
  const clearOptions = { path: '/', maxAge: 0 };
  response.cookies.set('oauth_state', '', clearOptions);
  response.cookies.set('oauth_code_verifier', '', clearOptions);
  response.cookies.set('oauth_redirect', '', clearOptions);

  return response;
}

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const code = searchParams.get('code');
  const state = searchParams.get('state');
  const error = searchParams.get('error');
  const errorDescription = searchParams.get('error_description');

  // Handle OAuth errors from the provider
  if (error) {
    logger.error(`[SSO] OAuth error: ${error} - ${errorDescription}`);
    return errorRedirect(request, errorDescription || error);
  }

  if (!code || !state) {
    return errorRedirect(request, 'Missing authorization code or state');
  }

  // Validate state parameter
  const storedState = request.cookies.get('oauth_state')?.value;
  if (!storedState || storedState !== state) {
    logger.warn('[SSO] State mismatch - possible CSRF attack');
    return errorRedirect(request, 'Invalid state parameter');
  }

  // Retrieve PKCE verifier
  const codeVerifier = request.cookies.get('oauth_code_verifier')?.value;
  if (!codeVerifier) {
    return errorRedirect(request, 'Missing PKCE verifier - session may have expired');
  }

  const postRedirect = request.cookies.get('oauth_redirect')?.value || '/';
  const callbackUrl = getCallbackUrl(request);

  // Exchange code for tokens
  let tokenData: {
    access_token: string;
    id_token?: string;
    token_type: string;
    expires_in?: number;
  };

  try {
    const tokenUrl = new URL('/api/v1/oauth/token', JANUA_BASE_URL);
    const tokenResponse = await fetch(tokenUrl.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: callbackUrl,
        client_id: CLIENT_ID,
        code_verifier: codeVerifier,
      }),
    });

    if (!tokenResponse.ok) {
      const errorBody = await tokenResponse.text();
      logger.error(`[SSO] Token exchange failed (${tokenResponse.status}): ${errorBody}`);
      return errorRedirect(request, 'Failed to exchange authorization code');
    }

    tokenData = await tokenResponse.json();
  } catch (err) {
    logger.error('[SSO] Token exchange error:', err);
    return errorRedirect(request, 'Authentication service unavailable');
  }

  // Fetch user info from Janua
  let userInfo: {
    sub: string;
    email?: string;
    name?: string;
    roles?: string[];
    role?: string | string[];
    org_id?: string;
  };

  try {
    const userInfoUrl = new URL('/api/v1/oauth/userinfo', JANUA_BASE_URL);
    const userInfoResponse = await fetch(userInfoUrl.toString(), {
      headers: { Authorization: `Bearer ${tokenData.access_token}` },
    });

    if (!userInfoResponse.ok) {
      const errorBody = await userInfoResponse.text();
      logger.error(`[SSO] UserInfo fetch failed (${userInfoResponse.status}): ${errorBody}`);
      return errorRedirect(request, 'Failed to retrieve user information');
    }

    userInfo = await userInfoResponse.json();
  } catch (err) {
    logger.error('[SSO] UserInfo error:', err);
    return errorRedirect(request, 'Failed to retrieve user information');
  }

  // Extract roles (support both array and single-value formats)
  const rolesRaw = userInfo.roles || userInfo.role || [];
  const roles: string[] = Array.isArray(rolesRaw)
    ? rolesRaw.filter((r): r is string => typeof r === 'string')
    : typeof rolesRaw === 'string'
      ? rolesRaw.split(',').map((r) => r.trim())
      : [];

  // Create session JWT
  let sessionToken: string;

  if (SESSION_SECRET) {
    // Sign a session JWT with the configured secret
    const secret = new TextEncoder().encode(SESSION_SECRET);
    sessionToken = await new SignJWT({
      sub: userInfo.sub,
      email: userInfo.email,
      name: userInfo.name,
      roles,
      org_id: userInfo.org_id,
      iss: 'selva-admin',
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt()
      .setExpirationTime('24h')
      .sign(secret);
  } else {
    // No secret configured: use the access token directly.
    // The middleware will still decode the payload for role checks.
    // In production, JANUA_SECRET_KEY MUST be set for proper session signing.
    logger.warn('[SSO] No SESSION_SECRET or JANUA_SECRET_KEY configured - using access token as session');
    sessionToken = tokenData.access_token;
  }

  // Redirect to the original destination
  const redirectUrl = new URL(postRedirect, request.url);
  const response = NextResponse.redirect(redirectUrl.toString());

  // Set session cookie
  const isProduction = process.env.NODE_ENV === 'production';
  response.cookies.set('janua-session', sessionToken, {
    path: '/',
    httpOnly: true,
    secure: isProduction,
    sameSite: 'lax',
    maxAge: 86400, // 24 hours
  });

  // Clear OAuth flow cookies
  const clearOptions = { path: '/', maxAge: 0 };
  response.cookies.set('oauth_state', '', clearOptions);
  response.cookies.set('oauth_code_verifier', '', clearOptions);
  response.cookies.set('oauth_redirect', '', clearOptions);

  return response;
}
