import { createSmeared, Smeared } from './smeared';

export const EXTERNAL_ID_PREFIX = 'spc:' as const;
export const PENDING_DELETE_PREFIX = 'spc:pending-delete:' as const;

const LEGACY_TYPE_PREFIXES = ['site:', 'subsite:', 'drive:', 'folder:', 'unknown:'] as const;

const LEGACY_SITE_PAGES_REGEX = new RegExp(`^${EXTERNAL_ID_PREFIX}[^/]+/sitePages$`);

// --- Legacy format types ---

interface LegacyRootId {
  type: 'root';
  siteId: string;
}

interface LegacySubsiteId {
  type: 'subsite';
  subsiteId: string;
}

interface LegacyDriveId {
  type: 'drive';
  siteId: string;
  driveId: string;
}

interface LegacyFolderId {
  type: 'folder';
  siteId: string;
  itemId: string;
}

interface LegacySitePagesId {
  type: 'sitePages';
  siteId: string;
}

interface LegacyUnknownId {
  type: 'unknown';
  // The opaque blob after `::` in the legacy format — originally `{path}-{uuid}`.
  // Treated as a single identifier during migration since the new format does
  // not require splitting it back apart.
  suffix: string;
}

export type ParsedLegacyExternalId =
  | LegacyRootId
  | LegacySubsiteId
  | LegacyDriveId
  | LegacyFolderId
  | LegacySitePagesId
  | LegacyUnknownId;

// --- Legacy format detection and parsing ---

export function isLegacyExternalId(externalId: string): boolean {
  if (!externalId.startsWith(EXTERNAL_ID_PREFIX)) {
    return false;
  }

  const afterPrefix = externalId.slice(EXTERNAL_ID_PREFIX.length);

  if (afterPrefix.startsWith('pending-delete:')) {
    return false;
  }

  for (const typePrefix of LEGACY_TYPE_PREFIXES) {
    if (afterPrefix.startsWith(typePrefix)) {
      return true;
    }
  }

  return LEGACY_SITE_PAGES_REGEX.test(externalId);
}

export function parseLegacyExternalId(externalId: string): ParsedLegacyExternalId | null {
  if (!isLegacyExternalId(externalId)) {
    return null;
  }

  const afterPrefix = externalId.slice(EXTERNAL_ID_PREFIX.length);

  if (afterPrefix.startsWith('site:')) {
    const siteId = afterPrefix.slice('site:'.length);
    if (siteId.includes('/')) {
      return null;
    }
    return { type: 'root', siteId };
  }

  if (afterPrefix.startsWith('subsite:')) {
    return { type: 'subsite', subsiteId: afterPrefix.slice('subsite:'.length) };
  }

  if (afterPrefix.startsWith('drive:')) {
    const rest = afterPrefix.slice('drive:'.length);
    const slashIndex = rest.indexOf('/');
    if (slashIndex === -1) {
      return null;
    }
    return {
      type: 'drive',
      siteId: rest.slice(0, slashIndex),
      driveId: rest.slice(slashIndex + 1),
    };
  }

  if (afterPrefix.startsWith('folder:')) {
    const rest = afterPrefix.slice('folder:'.length);
    const slashIndex = rest.indexOf('/');
    if (slashIndex === -1) {
      return null;
    }
    return {
      type: 'folder',
      siteId: rest.slice(0, slashIndex),
      itemId: rest.slice(slashIndex + 1),
    };
  }

  if (afterPrefix.startsWith('unknown:')) {
    const rest = afterPrefix.slice('unknown:'.length);
    const separatorIndex = rest.indexOf('::');
    if (separatorIndex === -1) {
      return null;
    }
    return { type: 'unknown', suffix: rest.slice(separatorIndex + 2) };
  }

  if (LEGACY_SITE_PAGES_REGEX.test(externalId)) {
    const siteId = afterPrefix.slice(0, afterPrefix.indexOf('/'));
    return { type: 'sitePages', siteId };
  }

  return null;
}

// --- New format builders ---

export function buildRootExternalId(rootSiteId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/site`);
}

export function buildSubsiteExternalId(rootSiteId: string, subsiteId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/subsite:${subsiteId}`);
}

export function buildDriveExternalId(rootSiteId: string, siteId: string, driveId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/drive:${siteId}/${driveId}`);
}

export function buildFolderExternalId(rootSiteId: string, siteId: string, itemId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/folder:${siteId}/${itemId}`);
}

export function buildSitePagesExternalId(rootSiteId: string, siteId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/sitePages:${siteId}`);
}

// Takes an arbitrary suffix (caller is responsible for uniqueness — typically
// `${path}-${randomUUID()}`). Keeping the suffix opaque lets migration reuse
// the existing legacy suffix verbatim without reconstructing it.
export function buildUnknownExternalId(rootSiteId: string, suffix: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/unknown:${suffix}`);
}

// --- Migration helper (legacy -> new) ---

export function migrateLegacyExternalId(rootSiteId: string, legacyExternalId: Smeared): Smeared {
  return legacyExternalId.transform((value) => {
    const parsed = parseLegacyExternalId(value);

    if (!parsed) {
      throw new Error(`Unrecognized legacy externalId format: ${value}`);
    }

    switch (parsed.type) {
      case 'root':
        return buildRootExternalId(rootSiteId).value;
      case 'subsite':
        return buildSubsiteExternalId(rootSiteId, parsed.subsiteId).value;
      case 'drive':
        return buildDriveExternalId(rootSiteId, parsed.siteId, parsed.driveId).value;
      case 'folder':
        return buildFolderExternalId(rootSiteId, parsed.siteId, parsed.itemId).value;
      case 'sitePages':
        return buildSitePagesExternalId(rootSiteId, parsed.siteId).value;
      case 'unknown':
        return buildUnknownExternalId(rootSiteId, parsed.suffix).value;
    }
  });
}
