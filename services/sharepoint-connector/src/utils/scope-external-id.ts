import { createSmeared, Smeared } from './smeared';

export const EXTERNAL_ID_PREFIX = 'spc:' as const;
export const PENDING_DELETE_PREFIX = 'spc:pending-delete:' as const;

const LEGACY_SITE_PAGES_REGEX = new RegExp(`^${EXTERNAL_ID_PREFIX}[^/]+/sitePages$`);

const NEW_ROOT_REGEX = new RegExp(`^${EXTERNAL_ID_PREFIX}([^/]+)/site$`);

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

// Returns true only when the externalId is a fully-parseable legacy format.
// Strings that merely start with a legacy type prefix but cannot be parsed
// (e.g. `spc:drive:no-slash`) return false so callers don't misclassify them
// as migratable.
export function isLegacyExternalId(externalId: string): boolean {
  return parseLegacyExternalId(externalId) !== null;
}

// Extracts the rootSiteId from a root scope externalId in either legacy
// (`spc:site:{id}`) or new (`spc:{id}/site`) format. Used to anchor scope
// grouping during migration so that partially-migrated sites still resolve
// their children under the same root.
export function extractRootSiteId(externalId: string): string | null {
  const legacy = parseLegacyExternalId(externalId);
  if (legacy?.type === 'root') {
    return legacy.siteId;
  }
  return externalId.match(NEW_ROOT_REGEX)?.[1] ?? null;
}

export function parseLegacyExternalId(externalId: string): ParsedLegacyExternalId | null {
  if (!externalId.startsWith(EXTERNAL_ID_PREFIX)) {
    return null;
  }

  const afterPrefix = externalId.slice(EXTERNAL_ID_PREFIX.length);

  if (afterPrefix.startsWith('pending-delete:')) {
    return null;
  }

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

// Prefix that matches every active (non-pending-delete) scope for a given root site.
export function buildActiveScopesPrefix(rootSiteId: string): Smeared {
  return createSmeared(`${EXTERNAL_ID_PREFIX}${rootSiteId}/`);
}

// Prefix that matches every stale (pending-delete) scope for a given root site.
export function buildStaleScopesPrefix(rootSiteId: string): Smeared {
  return createSmeared(`${PENDING_DELETE_PREFIX}${rootSiteId}/`);
}

// Moves an active externalId into the pending-delete namespace. Suffix is is preserved verbatim so
// operators can still identify the original scope type/site from the marker.
export function toPendingDeleteExternalId(activeExternalId: string): Smeared {
  return createSmeared(activeExternalId.replace(EXTERNAL_ID_PREFIX, PENDING_DELETE_PREFIX));
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
