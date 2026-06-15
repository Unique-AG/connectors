import { buildScopeExternalId } from '../../../src/utils/key-format';
import type {
  ScenarioAttachment,
  ScenarioPage,
  ScenarioSpace,
  ScenarioUniqueFile,
  ScenarioUniqueScope,
} from './scenario.types';

const DEFAULT_VERSION = '2026-05-01T10:00:00.000Z';
const DEFAULT_SPACE_KEY = 'SP';
const DEFAULT_SPACE_ID = 'space-1';
const DEFAULT_TENANT_NAME = 'tenant1';
const DEFAULT_INGEST_LABEL = 'ai-ingest';

/**
 * Entity builders that produce well-formed scenario primitives with sensible defaults.
 *
 * The override parameter lets tests focus on what matters:
 *
 *     page({ id: 'p1', body: '<p>Custom</p>' })
 *
 * instead of repeating spaceKey, labels, versionWhen, etc. on every page.
 */

export function space(overrides: Partial<ScenarioSpace> = {}): ScenarioSpace {
  return {
    id: 'space-1',
    key: DEFAULT_SPACE_KEY,
    name: 'Space One',
    ...overrides,
  };
}

export function page(overrides: Partial<ScenarioPage> & Pick<ScenarioPage, 'id'>): ScenarioPage {
  return {
    spaceKey: DEFAULT_SPACE_KEY,
    title: `Page ${overrides.id}`,
    body: `<p>Body of ${overrides.id}</p>`,
    labels: [DEFAULT_INGEST_LABEL],
    versionWhen: DEFAULT_VERSION,
    ...overrides,
  };
}

export function attachment(
  overrides: Partial<ScenarioAttachment> & Pick<ScenarioAttachment, 'id'>,
): ScenarioAttachment {
  return {
    title: `${overrides.id}.pdf`,
    mediaType: 'application/pdf',
    bytes: Buffer.from(`%PDF-1.4\n% fake bytes for ${overrides.id}\n%%EOF\n`),
    versionWhen: DEFAULT_VERSION,
    ...overrides,
  };
}

export function uniqueFile(
  overrides: Partial<ScenarioUniqueFile> & Pick<ScenarioUniqueFile, 'id' | 'key'>,
): ScenarioUniqueFile {
  return {
    byteSize: 64,
    mimeType: 'text/html',
    updatedAt: DEFAULT_VERSION,
    ...overrides,
  };
}

export function uniqueScope(
  overrides: Partial<ScenarioUniqueScope> & Pick<ScenarioUniqueScope, 'id' | 'name'>,
): ScenarioUniqueScope {
  return {
    parentId: null,
    externalId: null,
    ...overrides,
  };
}

/**
 * Domain-flavored shorthand for seeding a space scope under the configured root.
 * Produces the proper externalId (`confc:<tenant>:<spaceId>:<spaceKey>`) so that
 * `cleanupRemovedSpaces` can identify it the same way it does in production.
 */
export function spaceScope(opts: {
  spaceKey?: string;
  spaceId?: string;
  rootScopeId: string;
  tenantName?: string;
  scopeId?: string;
}): ScenarioUniqueScope {
  const spaceKey = opts.spaceKey ?? DEFAULT_SPACE_KEY;
  const spaceId = opts.spaceId ?? DEFAULT_SPACE_ID;
  return {
    id: opts.scopeId ?? `scope-${spaceKey}`,
    name: spaceKey,
    parentId: opts.rootScopeId,
    externalId: buildScopeExternalId(opts.tenantName ?? DEFAULT_TENANT_NAME, spaceId, spaceKey),
  };
}

/**
 * Domain-flavored shorthand for a Unique file representing a previously-ingested
 * Confluence page. Produces the same key the production code would generate
 * (`<tenant>/<spaceId>_<spaceKey>/<pageId>`).
 */
export function pageFile(opts: {
  pageId: string;
  spaceKey?: string;
  spaceId?: string;
  tenantName?: string;
  body?: string;
  /** Defaults to the same version as `page` so the file looks up-to-date. */
  updatedAt?: string;
  /** Scope this file belongs to (used by tenant-deletion's getContentIdsByScope). */
  scopeId?: string;
}): ScenarioUniqueFile {
  const spaceKey = opts.spaceKey ?? DEFAULT_SPACE_KEY;
  const spaceId = opts.spaceId ?? DEFAULT_SPACE_ID;
  const tenantName = opts.tenantName ?? DEFAULT_TENANT_NAME;
  const body = Buffer.from(opts.body ?? `<p>Stored body of ${opts.pageId}</p>`, 'utf-8');
  return {
    id: `content-${opts.pageId}`,
    key: `${tenantName}/${spaceId}_${spaceKey}/${opts.pageId}`,
    body,
    byteSize: body.byteLength,
    mimeType: 'text/html',
    updatedAt: opts.updatedAt ?? DEFAULT_VERSION,
    scopeId: opts.scopeId,
  };
}

/**
 * Domain-flavored shorthand for a Unique file representing a previously-ingested
 * Confluence attachment. Produces the production attachment key
 * (`<tenant>/<spaceId>_<spaceKey>/<pageId>::<attachmentId>`).
 */
export function attachmentFile(opts: {
  pageId: string;
  attachmentId: string;
  spaceKey?: string;
  spaceId?: string;
  tenantName?: string;
  bytes?: Buffer;
  mediaType?: string;
  updatedAt?: string;
  scopeId?: string;
}): ScenarioUniqueFile {
  const spaceKey = opts.spaceKey ?? DEFAULT_SPACE_KEY;
  const spaceId = opts.spaceId ?? DEFAULT_SPACE_ID;
  const tenantName = opts.tenantName ?? DEFAULT_TENANT_NAME;
  const bytes = opts.bytes ?? Buffer.from(`stored bytes of ${opts.attachmentId}`);
  return {
    id: `content-${opts.pageId}-${opts.attachmentId}`,
    key: `${tenantName}/${spaceId}_${spaceKey}/${opts.pageId}::${opts.attachmentId}`,
    body: bytes,
    byteSize: bytes.byteLength,
    mimeType: opts.mediaType ?? 'application/pdf',
    updatedAt: opts.updatedAt ?? DEFAULT_VERSION,
    scopeId: opts.scopeId,
  };
}
