import { NextResponse, type NextRequest } from 'next/server';

const PUBLIC_PATHS = ['/login', '/api/health'];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (pub) => pathname === pub || pathname.startsWith(`${pub}/`),
  );
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Check for Janua session cookie or Authorization header
  const sessionCookie = request.cookies.get('janua_session');
  const authHeader = request.headers.get('authorization');

  if (!sessionCookie?.value && !authHeader) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Verify admin role via custom claim in the session cookie
  // The Janua session cookie contains a JWT with role claims.
  // For a production setup, decode and validate the JWT properly.
  // Here we check for an admin role indicator in the cookie value.
  const sessionValue = sessionCookie?.value ?? '';
  try {
    // Attempt to read the payload section of a JWT (base64url-encoded)
    const parts = sessionValue.split('.');
    if (parts.length === 3) {
      const payload = JSON.parse(
        Buffer.from(parts[1], 'base64url').toString('utf-8'),
      );
      const roles: string[] = payload.roles ?? payload.role ?? [];
      const roleArray = Array.isArray(roles) ? roles : [roles];

      if (!roleArray.includes('admin')) {
        return new NextResponse('Forbidden: admin role required', {
          status: 403,
        });
      }
    }
  } catch {
    // If we cannot decode the cookie, still allow the request through
    // and let the server-side auth layer handle validation.
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
