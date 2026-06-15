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
  updatedAt: string;
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
