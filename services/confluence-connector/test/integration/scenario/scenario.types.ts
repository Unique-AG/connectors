import type { TenantConfig } from '../../../src/config';
import type { ContentType } from '../../../src/confluence-api';

export type InstanceDescriptor =
  | { type: 'cloud'; cloudId: string; baseUrl: string }
  | { type: 'data-center'; baseUrl: string };

export interface ScenarioTenantConfig {
  name: string;
  instance: InstanceDescriptor;
  ingestSingleLabel: string;
  ingestAllLabel: string;
  rootScopeId: string;
  rootScopeName: string;
  useV1KeyFormat: boolean;
  storeInternally: boolean;
  imageOcrEnabled: boolean;
  attachmentsEnabled: boolean;
  allowedMimeTypes: string[];
  maxFileSizeMb: number;
  concurrency: number;
  maxItemsToScan: number | undefined;
}

export interface ScenarioSpace {
  id: string;
  key: string;
  name: string;
}

export interface ScenarioAttachment {
  id: string;
  title: string;
  mediaType: string;
  bytes: Buffer;
  versionWhen?: string;
}

export interface ScenarioPage {
  id: string;
  spaceKey: string;
  title: string;
  body: string;
  labels: string[];
  parentId?: string;
  versionWhen: string;
  attachments?: ScenarioAttachment[];
  /**
   * Confluence content type. Defaults to `page`. Use `blogpost` to test blog
   * post ingestion, or `database` / `whiteboard` / `embed` to test that the
   * scanner skips these types (descendants are still discoverable via
   * `parentId`, which is exercised by `content-types.integration-spec.ts`).
   */
  type?: ContentType;
}

export interface ScenarioConfluence {
  spaces: ScenarioSpace[];
  pages: ScenarioPage[];
}

export interface ScenarioUniqueScope {
  id: string;
  name: string;
  parentId: string | null;
  externalId: string | null;
}

export interface ScenarioUniqueFile {
  id: string;
  key: string;
  byteSize: number;
  mimeType: string;
  metadata?: Record<string, string>;
  body?: Buffer;
  /**
   * ISO timestamp the file was last updated in Unique.
   * Compared against the page's `versionWhen` by `performFileDiff` to decide
   * whether the file is up-to-date (no change), older (updated), or missing (new).
   * Defaults to epoch zero so any real page wins by default — set this when you
   * want to test "no-change" or "older Unique data" scenarios.
   */
  updatedAt?: string;
  /**
   * Scope the file belongs to in Unique (`SCOPE` ownerId). Used by
   * `files.getContentIdsByScope`, which the tenant-deletion flow relies on.
   * Set this when seeding files for delete-tenant or scope-targeted tests.
   */
  scopeId?: string;
}

export interface ScenarioUnique {
  scopes: ScenarioUniqueScope[];
  files: ScenarioUniqueFile[];
  currentUserId: string;
}

export interface Scenario {
  tenant: ScenarioTenantConfig;
  confluence: ScenarioConfluence;
  unique: ScenarioUnique;
}

/** Resolved tenant config in the same shape used by the production services. */
export type ResolvedTenantConfig = TenantConfig;
