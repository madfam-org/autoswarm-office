'use client';

/**
 * useIsMadfamAdmin — default-deny admin gate for the Atrium.
 *
 * Reads the Janua session cookie (decoded by `getSessionUser`) and
 * returns `true` IFF either:
 *   - claims.email === 'admin@madfam.io', or
 *   - claims.role === 'superadmin' (singular — some IdPs use this), or
 *   - claims.roles contains 'superadmin' (plural — Janua's canonical
 *     shape).
 *
 * Any deviation — missing token, malformed token, parse failure,
 * unknown claim shape — resolves to `false`. There is no SSR fallback
 * (the cookie is browser-only); during SSR we return `false` as well.
 *
 * SECURITY NOTE: this is UI-side gating only. The real authorization
 * boundary is the target service (Janua, Karafiel admin, etc.) which
 * re-validates the JWT on every request. The hook exists so we don't
 * render admin entry points for users who clearly aren't admins, not
 * to enforce authorization.
 */

import { useEffect, useState } from 'react';
import { getSessionUser } from '@/lib/api';

const ADMIN_EMAIL = 'admin@madfam.io';
const SUPERADMIN_ROLE = 'superadmin';

/**
 * Pure predicate over a parsed-JWT-claims object. Exported for tests
 * so we can exhaustively cover the default-deny surface without
 * round-tripping through the cookie reader.
 *
 * Default-deny invariant: any input shape we don't explicitly recognize
 * MUST return false. Unknown is not admin.
 */
export function isMadfamAdminClaims(claims: unknown): boolean {
  if (claims == null || typeof claims !== 'object') return false;
  const c = claims as Record<string, unknown>;

  // Email-based gate. Strict equality, lowercased input.
  const email = typeof c.email === 'string' ? c.email.trim().toLowerCase() : '';
  if (email === ADMIN_EMAIL) return true;

  // Singular `role` field (some IdPs use this shape).
  const singleRole = typeof c.role === 'string' ? c.role.trim().toLowerCase() : '';
  if (singleRole === SUPERADMIN_ROLE) return true;

  // Plural `roles` array (Janua's canonical shape).
  if (Array.isArray(c.roles)) {
    for (const r of c.roles) {
      if (typeof r === 'string' && r.trim().toLowerCase() === SUPERADMIN_ROLE) {
        return true;
      }
    }
  }

  return false;
}

export function useIsMadfamAdmin(): boolean {
  // SSR-safe: start as false. Even if this flickers for a frame on
  // hydration, default-deny means we never accidentally show admin
  // surfaces to a user who turned out not to be an admin.
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    try {
      const user = getSessionUser();
      setIsAdmin(isMadfamAdminClaims(user));
    } catch {
      setIsAdmin(false);
    }
  }, []);

  return isAdmin;
}
