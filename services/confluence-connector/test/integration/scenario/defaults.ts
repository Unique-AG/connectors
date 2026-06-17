/**
 * Shared defaults for the scenario builders. Kept in one place so the
 * Confluence-side and Unique-side builders agree on values (e.g. a page file's
 * `updatedAt` matches the page's `versionWhen`, so it looks up-to-date).
 */
export const DEFAULT_VERSION = '2026-05-01T10:00:00.000Z';
export const DEFAULT_SPACE_KEY = 'SP';
export const DEFAULT_SPACE_ID = 'space-1';
export const DEFAULT_SPACE_NAME = 'Space One';
export const DEFAULT_TENANT_NAME = 'tenant1';
export const DEFAULT_INGEST_LABEL = 'ai-ingest';
export const DEFAULT_INGEST_ALL_LABEL = 'ai-ingest-all';
export const DEFAULT_ROOT_SCOPE_ID = 'root-scope-id';
export const DEFAULT_ROOT_SCOPE_NAME = 'Confluence';
