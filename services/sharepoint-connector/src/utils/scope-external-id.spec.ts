import { describe, expect, it } from 'vitest';
import {
  buildDriveExternalId,
  buildFolderExternalId,
  buildRootExternalId,
  buildSitePagesExternalId,
  buildSubsiteExternalId,
  buildUnknownExternalId,
  extractRootSiteId,
  isLegacyExternalId,
  migrateLegacyExternalId,
  parseLegacyExternalId,
} from './scope-external-id';
import { createSmeared } from './smeared';

const ROOT_SITE_ID = 'root-site-id-123';

const LEGACY_IDS = {
  root: 'spc:site:site-id-abc',
  subsite: 'spc:subsite:subsite-id-def',
  drive: 'spc:drive:site-id-abc/drive-id-456',
  folder: 'spc:folder:site-id-abc/item-id-789',
  sitePages: 'spc:site-id-abc/sitePages',
  unknown: 'spc:unknown:site-id-abc::/some/path-0123abcd',
};

const NEW_IDS = {
  root: `spc:${ROOT_SITE_ID}/site`,
  subsite: `spc:${ROOT_SITE_ID}/subsite:subsite-id-def`,
  drive: `spc:${ROOT_SITE_ID}/drive:site-id-abc/drive-id-456`,
  folder: `spc:${ROOT_SITE_ID}/folder:site-id-abc/item-id-789`,
  sitePages: `spc:${ROOT_SITE_ID}/sitePages:site-id-abc`,
  unknown: `spc:${ROOT_SITE_ID}/unknown:/some/path-0123abcd`,
};

describe('isLegacyExternalId', () => {
  it.each([
    ['root', LEGACY_IDS.root],
    ['subsite', LEGACY_IDS.subsite],
    ['drive', LEGACY_IDS.drive],
    ['folder', LEGACY_IDS.folder],
    ['sitePages', LEGACY_IDS.sitePages],
    ['unknown', LEGACY_IDS.unknown],
  ])('returns true for legacy %s format', (_type, id) => {
    expect(isLegacyExternalId(id)).toBe(true);
  });

  it.each([
    ['root', NEW_IDS.root],
    ['subsite', NEW_IDS.subsite],
    ['drive', NEW_IDS.drive],
    ['folder', NEW_IDS.folder],
    ['sitePages', NEW_IDS.sitePages],
    ['unknown', NEW_IDS.unknown],
  ])('returns false for new %s format', (_type, id) => {
    expect(isLegacyExternalId(id)).toBe(false);
  });

  it('returns false for pending-delete format', () => {
    expect(isLegacyExternalId(`spc:pending-delete:${ROOT_SITE_ID}/site`)).toBe(false);
  });

  it('returns false for empty string', () => {
    expect(isLegacyExternalId('')).toBe(false);
  });

  it('returns false for non-spc prefix', () => {
    expect(isLegacyExternalId('other:site:abc')).toBe(false);
  });

  // `isLegacyExternalId` must only return true when the id is fully parseable.
  // Otherwise a malformed legacy id would satisfy the detection check, the
  // migration step would then throw on parse, and a single corrupt row would
  // block the whole site's sync.
  it.each([
    ['drive missing slash', 'spc:drive:no-slash-here'],
    ['folder missing slash', 'spc:folder:no-slash-here'],
    ['unknown missing separator', 'spc:unknown:no-double-colon'],
    ['root with slash in siteId', 'spc:site:abc/xyz'],
  ])('returns false for malformed legacy-like id (%s)', (_desc, id) => {
    expect(isLegacyExternalId(id)).toBe(false);
  });
});

describe('extractRootSiteId', () => {
  it('extracts siteId from legacy root externalId', () => {
    expect(extractRootSiteId('spc:site:site-id-abc')).toBe('site-id-abc');
  });

  it('extracts siteId from new-format root externalId', () => {
    expect(extractRootSiteId('spc:site-id-abc/site')).toBe('site-id-abc');
  });

  it('returns null for non-root externalIds', () => {
    expect(extractRootSiteId(LEGACY_IDS.drive)).toBeNull();
    expect(extractRootSiteId(NEW_IDS.drive)).toBeNull();
    expect(extractRootSiteId('spc:site-id-abc/subsite:foo')).toBeNull();
  });

  it('returns null for empty or unrelated strings', () => {
    expect(extractRootSiteId('')).toBeNull();
    expect(extractRootSiteId('other:site:abc')).toBeNull();
  });
});

describe('parseLegacyExternalId', () => {
  it('parses root format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.root)).toEqual({
      type: 'root',
      siteId: 'site-id-abc',
    });
  });

  it('parses subsite format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.subsite)).toEqual({
      type: 'subsite',
      subsiteId: 'subsite-id-def',
    });
  });

  it('parses drive format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.drive)).toEqual({
      type: 'drive',
      siteId: 'site-id-abc',
      driveId: 'drive-id-456',
    });
  });

  it('parses folder format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.folder)).toEqual({
      type: 'folder',
      siteId: 'site-id-abc',
      itemId: 'item-id-789',
    });
  });

  it('parses sitePages format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.sitePages)).toEqual({
      type: 'sitePages',
      siteId: 'site-id-abc',
    });
  });

  it('parses unknown format', () => {
    expect(parseLegacyExternalId(LEGACY_IDS.unknown)).toEqual({
      type: 'unknown',
      suffix: '/some/path-0123abcd',
    });
  });

  it('returns null for new-format externalIds', () => {
    expect(parseLegacyExternalId(NEW_IDS.root)).toBeNull();
  });

  it('returns null for pending-delete format', () => {
    expect(parseLegacyExternalId(`spc:pending-delete:${ROOT_SITE_ID}/site`)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(parseLegacyExternalId('')).toBeNull();
  });

  it('returns null for drive format missing separator', () => {
    expect(parseLegacyExternalId('spc:drive:no-slash-here')).toBeNull();
  });

  it('returns null for folder format missing separator', () => {
    expect(parseLegacyExternalId('spc:folder:no-slash-here')).toBeNull();
  });

  it('returns null for unknown format missing separator', () => {
    expect(parseLegacyExternalId('spc:unknown:no-double-colon')).toBeNull();
  });

  it('returns null for root format with slash in siteId', () => {
    expect(parseLegacyExternalId('spc:site:abc/xyz')).toBeNull();
  });
});

describe('migrateLegacyExternalId', () => {
  it.each([
    ['root', LEGACY_IDS.root, NEW_IDS.root],
    ['subsite', LEGACY_IDS.subsite, NEW_IDS.subsite],
    ['drive', LEGACY_IDS.drive, NEW_IDS.drive],
    ['folder', LEGACY_IDS.folder, NEW_IDS.folder],
    ['sitePages', LEGACY_IDS.sitePages, NEW_IDS.sitePages],
    ['unknown', LEGACY_IDS.unknown, NEW_IDS.unknown],
  ])('converts legacy %s to new format', (_type, legacy, expected) => {
    const result = migrateLegacyExternalId(ROOT_SITE_ID, createSmeared(legacy));
    expect(result.value).toBe(expected);
  });

  it('returns a Smeared preserving the active flag', () => {
    const inactive = migrateLegacyExternalId(ROOT_SITE_ID, createSmeared(LEGACY_IDS.root));
    expect(inactive).toHaveProperty('value');
    expect(inactive).toHaveProperty('active');
  });

  it('throws for unrecognized format', () => {
    expect(() => migrateLegacyExternalId(ROOT_SITE_ID, createSmeared('garbage'))).toThrow(
      'Unrecognized legacy externalId format: garbage',
    );
  });

  it('throws for new-format input (not idempotent by design)', () => {
    expect(() => migrateLegacyExternalId(ROOT_SITE_ID, createSmeared(NEW_IDS.root))).toThrow(
      'Unrecognized legacy externalId format',
    );
  });

  it('throws for pending-delete format', () => {
    expect(() =>
      migrateLegacyExternalId(
        ROOT_SITE_ID,
        createSmeared(`spc:pending-delete:${ROOT_SITE_ID}/site`),
      ),
    ).toThrow('Unrecognized legacy externalId format');
  });

  it('throws for drive format missing separator', () => {
    expect(() =>
      migrateLegacyExternalId(ROOT_SITE_ID, createSmeared('spc:drive:no-slash-here')),
    ).toThrow('Unrecognized legacy externalId format');
  });
});

describe('buildRootExternalId', () => {
  it('builds new-format root externalId', () => {
    expect(buildRootExternalId('site-abc').value).toBe('spc:site-abc/site');
  });
});

describe('buildSubsiteExternalId', () => {
  it('builds new-format subsite externalId', () => {
    expect(buildSubsiteExternalId('root-abc', 'subsite-def').value).toBe(
      'spc:root-abc/subsite:subsite-def',
    );
  });
});

describe('buildDriveExternalId', () => {
  it('builds new-format drive externalId', () => {
    expect(buildDriveExternalId('root-abc', 'site-abc', 'drive-456').value).toBe(
      'spc:root-abc/drive:site-abc/drive-456',
    );
  });
});

describe('buildFolderExternalId', () => {
  it('builds new-format folder externalId', () => {
    expect(buildFolderExternalId('root-abc', 'site-abc', 'item-789').value).toBe(
      'spc:root-abc/folder:site-abc/item-789',
    );
  });
});

describe('buildSitePagesExternalId', () => {
  it('builds new-format sitePages externalId', () => {
    expect(buildSitePagesExternalId('root-abc', 'site-abc').value).toBe(
      'spc:root-abc/sitePages:site-abc',
    );
  });
});

describe('buildUnknownExternalId', () => {
  it('builds new-format unknown externalId with arbitrary suffix', () => {
    expect(buildUnknownExternalId('root-abc', '/some/path-fixed-suffix').value).toBe(
      'spc:root-abc/unknown:/some/path-fixed-suffix',
    );
  });
});
