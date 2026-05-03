/**
 * Authenticated API client for the Nexus API (admin app).
 *
 * Reads the `janua-session` cookie and passes it as a Bearer token.
 * All API calls go through this function so auth is handled once.
 *
 * Mirrors the office-ui pattern at `apps/office-ui/src/lib/api.ts`.
 * Uses `NEXT_PUBLIC_NEXUS_API_URL` (admin's env convention) instead of
 * office-ui's `NEXT_PUBLIC_API_URL`.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_NEXUS_API_URL ?? 'http://localhost:4300';

export function getAuthToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)janua-session=([^;]*)/);
  return match?.[1] ?? null;
}

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  });
}
