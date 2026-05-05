import { NextResponse, type NextRequest } from 'next/server';

/**
 * URL scheme:
 *   selva.town       → Landing page (public)
 *   app.selva.town   → Virtual office app (auth required for /office)
 */

const APP_HOST = 'app.selva.town';
const LANDING_HOST = 'selva.town';

const PUBLIC_PATHS = ['/', '/login', '/guest', '/demo', '/api/health', '/api/auth'];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (pub) => pathname === pub || pathname.startsWith(`${pub}/`),
  );
}

function isAppHost(host: string): boolean {
  return host === APP_HOST || host.startsWith(APP_HOST);
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = request.headers.get('host') || '';

  // --- App host (app.selva.town) ---
  // Redirect root to /office, allow /demo and /login as entry points
  if (isAppHost(host) && pathname === '/') {
    return NextResponse.redirect(new URL('/office', request.url));
  }

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Check for Janua session cookie or Authorization header
  const sessionCookie = request.cookies.get('janua-session');
  const authHeader = request.headers.get('authorization');

  if (!sessionCookie?.value && !authHeader) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico (favicon)
     * - public folder assets
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
