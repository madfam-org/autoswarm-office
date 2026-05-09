import { describe, it, expect } from 'vitest';
import {
  ATRIUM_CATALOG,
  getPlatformBySlug,
  resolveLaunchUrl,
  visibleCatalog,
  type AtriumPlatform,
} from '../catalog';

describe('ATRIUM_CATALOG shape', () => {
  it('contains all 14 platforms from the spec', () => {
    const expected = [
      'karafiel',
      'dhanam',
      'forgesight',
      'tezca',
      'fortuna',
      'rondelio',
      'janua',
      'enclii',
      'selva',
      'phynd-crm',
      'cotiza',
      'pravara-mes',
      'sim4d',
      'ceq',
    ];
    const actual = ATRIUM_CATALOG.map((p) => p.slug);
    expect(actual).toEqual(expect.arrayContaining(expected));
    expect(actual).toHaveLength(expected.length);
  });

  it('every entry has a non-empty slug, displayName, tagline, and tier', () => {
    for (const entry of ATRIUM_CATALOG) {
      expect(entry.slug).toBeTruthy();
      expect(entry.displayName).toBeTruthy();
      expect(entry.tagline).toBeTruthy();
      expect(['self-serve', 'platform', 'ecosystem-service']).toContain(
        entry.tier,
      );
    }
  });

  it('slugs are unique', () => {
    const slugs = ATRIUM_CATALOG.map((p) => p.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('all URL fields, when present, are absolute https URLs', () => {
    for (const entry of ATRIUM_CATALOG) {
      for (const url of [
        entry.appUrl,
        entry.adminUrl,
        entry.publicUrl,
        entry.apiUrl,
      ]) {
        if (url !== undefined) {
          expect(url).toMatch(/^https:\/\//);
        }
      }
    }
  });
});

describe('getPlatformBySlug', () => {
  it('returns the matching entry', () => {
    const entry = getPlatformBySlug('karafiel');
    expect(entry?.displayName).toBe('Karafiel');
  });

  it('returns undefined for unknown slugs', () => {
    expect(getPlatformBySlug('not-a-real-slug')).toBeUndefined();
  });
});

describe('resolveLaunchUrl', () => {
  const fullEntry: AtriumPlatform = {
    slug: 't',
    displayName: 'T',
    tagline: '',
    tier: 'platform',
    appUrl: 'https://app.example',
    adminUrl: 'https://admin.example',
    publicUrl: 'https://public.example',
  };

  it('returns appUrl for default app variant', () => {
    expect(resolveLaunchUrl(fullEntry)).toBe('https://app.example');
  });

  it('returns adminUrl when variant=admin', () => {
    expect(resolveLaunchUrl(fullEntry, 'admin')).toBe('https://admin.example');
  });

  it('returns publicUrl when variant=public', () => {
    expect(resolveLaunchUrl(fullEntry, 'public')).toBe(
      'https://public.example',
    );
  });

  it('falls back to publicUrl when appUrl is missing for app variant', () => {
    const entry: AtriumPlatform = {
      slug: 'fortuna',
      displayName: 'F',
      tagline: '',
      tier: 'self-serve',
      publicUrl: 'https://fortuna.tube',
    };
    expect(resolveLaunchUrl(entry, 'app')).toBe('https://fortuna.tube');
  });

  it('returns undefined when no URL is available', () => {
    const entry: AtriumPlatform = {
      slug: 'dry',
      displayName: 'D',
      tagline: '',
      tier: 'ecosystem-service',
    };
    expect(resolveLaunchUrl(entry, 'app')).toBeUndefined();
    expect(resolveLaunchUrl(entry, 'admin')).toBeUndefined();
    expect(resolveLaunchUrl(entry, 'public')).toBeUndefined();
  });

  it('admin variant falls through to app when adminUrl missing', () => {
    const entry: AtriumPlatform = {
      slug: 't',
      displayName: 'T',
      tagline: '',
      tier: 'platform',
      appUrl: 'https://app.example',
    };
    expect(resolveLaunchUrl(entry, 'admin')).toBe('https://app.example');
  });
});

describe('visibleCatalog', () => {
  it('returns all entries for admins', () => {
    expect(visibleCatalog(true)).toHaveLength(ATRIUM_CATALOG.length);
  });

  it('hides adminOnly entries from non-admins', () => {
    // Sanity: as of writing no entries are flagged adminOnly, so the
    // non-admin view equals the full catalog.
    const visible = visibleCatalog(false);
    for (const entry of visible) {
      expect(entry.adminOnly).not.toBe(true);
    }
  });
});
