import type { FileAccessInput, UniqueFile } from '../files/files.types';
import type { Group, GroupWithMembers } from '../groups/groups.types';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
} from '../ingestion/ingestion.types';
import type { Scope, ScopeAccess } from '../scopes/scopes.types';
import type { SimpleUser } from '../users/users.types';

export interface RequestMetricAttributes {
  operation: string;
  target: string;
  result: 'success' | 'error';
  status_code_class?: string;
  tenant?: string;
}

export type UniqueEntityType = 'GROUP' | 'USER';

export type UniqueAccessType = 'MANAGE' | 'READ' | 'WRITE';

export const UniqueOwnerType = {
  Scope: 'SCOPE',
  Company: 'COMPANY',
  User: 'USER',
  Chat: 'CHAT',
} as const;

export type UniqueOwnerType = (typeof UniqueOwnerType)[keyof typeof UniqueOwnerType];

export interface ClusterLocalAuthConfig {
  mode: 'cluster_local';
  serviceId: string;
  extraHeaders: Record<string, string>;
}

export interface ExternalAuthConfig {
  mode: 'external';
  zitadelOauthTokenUrl: string;
  zitadelClientId: string;
  zitadelClientSecret: string;
  zitadelProjectId: string;
}

export type UniqueApiClientAuthConfig = ClusterLocalAuthConfig | ExternalAuthConfig;

export interface UniqueApiClientConfig {
  auth: UniqueApiClientAuthConfig;
  endpoints: {
    scopeManagementBaseUrl: string;
    ingestionBaseUrl: string;
  };
  rateLimitPerMinute?: number;
  fetch?: typeof fetch;
  metadata?: {
    clientName?: string;
    tenantKey?: string;
  };
}

export interface UniqueApiObservabilityConfig {
  loggerContext?: string;
  metricPrefix?: string;
  includeTenantDimension?: boolean;
}

export interface UniqueApiModuleOptions {
  observability?: UniqueApiObservabilityConfig;
  defaultClient?: UniqueApiClientConfig;
}

export interface ContentUpdateResult {
  id: string;
  ownerId: string;
  ownerType: string;
}

export interface DeleteFolderResult {
  successFolders: Array<{
    id: string;
    name: string;
    path: string;
  }>;
  failedFolders: Array<{
    id: string;
    name: string;
    failReason: string;
    path: string;
  }>;
}

export interface UniqueApiClient {
  auth: {
    getToken(): Promise<string>;
  };
  scopes: {
    createFromPaths(
      paths: string[],
      opts?: { includePermissions?: boolean; inheritAccess?: boolean },
    ): Promise<Scope[]>;
    getById(id: string): Promise<Scope | null>;
    getByExternalId(externalId: string): Promise<Scope | null>;
    updateExternalId(
      scopeId: string,
      externalId: string,
    ): Promise<{ id: string; externalId: string | null }>;
    updateParent(
      scopeId: string,
      newParentId: string,
    ): Promise<{ id: string; parentId: string | null }>;
    listChildren(parentId: string): Promise<Scope[]>;
    createAccesses(
      scopeId: string,
      accesses: ScopeAccess[],
      applyToSubScopes?: boolean,
    ): Promise<void>;
    deleteAccesses(
      scopeId: string,
      accesses: ScopeAccess[],
      applyToSubScopes?: boolean,
    ): Promise<void>;
    delete(
      scopeId: string,
      options?: { recursive?: boolean },
    ): Promise<DeleteFolderResult>;
  };
  files: {
    getByKeys(keys: string[]): Promise<UniqueFile[]>;
    getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]>;
    getCountByKeyPrefix(keyPrefix: string): Promise<number>;
    move(
      contentId: string,
      newOwnerId: string,
      newUrl: string,
    ): Promise<ContentUpdateResult>;
    delete(contentId: string): Promise<boolean>;
    deleteByKeyPrefix(keyPrefix: string): Promise<number>;
    addAccesses(
      scopeId: string,
      fileAccesses: FileAccessInput[],
    ): Promise<number>;
    removeAccesses(
      scopeId: string,
      fileAccesses: FileAccessInput[],
    ): Promise<number>;
  };
  users: {
    listAll(): Promise<SimpleUser[]>;
    getCurrentId(): Promise<string>;
  };
  groups: {
    listByExternalIdPrefix(
      externalIdPrefix: string,
    ): Promise<GroupWithMembers[]>;
    create(group: {
      name: string;
      externalId: string;
    }): Promise<GroupWithMembers>;
    update(group: { id: string; name: string }): Promise<Group>;
    delete(groupId: string): Promise<void>;
    addMembers(groupId: string, memberIds: string[]): Promise<void>;
    removeMembers(groupId: string, userIds: string[]): Promise<void>;
  };
  ingestion: {
    registerContent(
      request: ContentRegistrationRequest,
    ): Promise<IngestionApiResponse>;
    finalizeIngestion(
      request: IngestionFinalizationRequest,
    ): Promise<{ id: string }>;
    performFileDiff(
      fileList: FileDiffItem[],
      partialKey: string,
    ): Promise<FileDiffResponse>;
  };
  close?(): Promise<void>;
}

export interface UniqueApiClientFactory {
  create(config: UniqueApiClientConfig): UniqueApiClient;
}

export interface UniqueApiClientRegistry {
  get(key: string): UniqueApiClient | undefined;
  getOrCreate(
    key: string,
    config: UniqueApiClientConfig,
  ): Promise<UniqueApiClient>;
  set(key: string, client: UniqueApiClient): void;
  delete(key: string): Promise<void>;
  clear(): Promise<void>;
}
