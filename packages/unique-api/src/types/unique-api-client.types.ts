import type { UniqueApiAuth } from './unique-api-auth.types';
import type { UniqueApiFiles } from './unique-api-files.types';
import type { UniqueApiGroups } from './unique-api-groups.types';
import type { UniqueApiIngestion } from './unique-api-ingestion.types';
import type { UniqueApiClientConfig } from './unique-api-module.types';
import type { UniqueApiScopes } from './unique-api-scopes.types';
import type { UniqueApiUsers } from './unique-api-users.types';

export interface UniqueApiClient {
  auth: UniqueApiAuth;
  scopes: UniqueApiScopes;
  files: UniqueApiFiles;
  users: UniqueApiUsers;
  groups: UniqueApiGroups;
  ingestion: UniqueApiIngestion;
  close?(): Promise<void>;
}

export interface UniqueApiClientFactory {
  create(config: UniqueApiClientConfig): UniqueApiClient;
}

export interface UniqueApiClientRegistry {
  get(key: string): UniqueApiClient | undefined;
  getOrCreate(key: string, config: UniqueApiClientConfig): UniqueApiClient;
  set(key: string, client: UniqueApiClient): void;
  delete(key: string): Promise<void>;
  clear(): Promise<void>;
}
