import { describe, it, expect } from 'vitest';
import { isMadfamAdminClaims } from '../useIsMadfamAdmin';

describe('isMadfamAdminClaims — default-deny gate', () => {
  it('returns false for null', () => {
    expect(isMadfamAdminClaims(null)).toBe(false);
  });

  it('returns false for undefined', () => {
    expect(isMadfamAdminClaims(undefined)).toBe(false);
  });

  it('returns false for non-objects', () => {
    expect(isMadfamAdminClaims('admin@madfam.io')).toBe(false);
    expect(isMadfamAdminClaims(42)).toBe(false);
    expect(isMadfamAdminClaims(true)).toBe(false);
  });

  it('returns false for empty objects', () => {
    expect(isMadfamAdminClaims({})).toBe(false);
  });

  it('returns true for the canonical admin email', () => {
    expect(isMadfamAdminClaims({ email: 'admin@madfam.io' })).toBe(true);
  });

  it('matches the admin email case-insensitively', () => {
    expect(isMadfamAdminClaims({ email: 'Admin@MadFam.IO' })).toBe(true);
  });

  it('returns false for non-admin emails', () => {
    expect(isMadfamAdminClaims({ email: 'someone@madfam.io' })).toBe(false);
    expect(isMadfamAdminClaims({ email: 'admin@evil.com' })).toBe(false);
  });

  it('honors singular role=superadmin', () => {
    expect(isMadfamAdminClaims({ role: 'superadmin' })).toBe(true);
    expect(isMadfamAdminClaims({ role: 'SUPERADMIN' })).toBe(true);
  });

  it('honors plural roles array containing superadmin', () => {
    expect(isMadfamAdminClaims({ roles: ['user', 'superadmin'] })).toBe(true);
  });

  it('returns false for a roles array without superadmin', () => {
    expect(isMadfamAdminClaims({ roles: ['user', 'admin'] })).toBe(false);
    expect(isMadfamAdminClaims({ roles: [] })).toBe(false);
  });

  it('returns false for malformed roles (non-array, non-string members)', () => {
    expect(isMadfamAdminClaims({ roles: 'superadmin' })).toBe(false);
    expect(isMadfamAdminClaims({ roles: [42, true, null] })).toBe(false);
  });

  it('default-denies when the claims shape is unknown', () => {
    // Some adversarial-looking shapes that should NOT slip through.
    expect(isMadfamAdminClaims({ admin: true })).toBe(false);
    expect(isMadfamAdminClaims({ isAdmin: true })).toBe(false);
    expect(isMadfamAdminClaims({ permissions: ['*'] })).toBe(false);
  });
});
