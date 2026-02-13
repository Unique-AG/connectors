export { UniqueApiModule } from './core/unique-api.module';

export {
  UNIQUE_API_CLIENT_FACTORY,
  UNIQUE_API_CLIENT_REGISTRY,
  UNIQUE_API_METRICS,
  getUniqueApiClientToken,
} from './core/tokens';

export type {
  UniqueApiClient,
  UniqueApiClientConfig,
  UniqueApiClientFactory,
  UniqueApiClientRegistry,
  UniqueApiModuleOptions,
  UniqueApiModuleAsyncOptions,
  UniqueApiFeatureAsyncOptions,
  UniqueApiObservabilityConfig,
  UniqueAccessType,
  UniqueEntityType,
  ClusterLocalAuthConfig,
  ExternalAuthConfig,
  UniqueApiClientAuthConfig,
  ContentUpdateResult,
  DeleteFolderResult,
} from './core/types';

export { UniqueOwnerType } from './core/types';

export type { UniqueApiMetrics } from './core/observability';

export type { Scope, ScopeAccess, ScopeWithPath } from './scopes/scopes.types';
export type { UniqueFile, FileAccessInput, FileAccessKey } from './files/files.types';
export type { SimpleUser } from './users/users.types';
export type { Group, GroupWithMembers } from './groups/groups.types';
export type {
  ContentRegistrationRequest,
  IngestionFinalizationRequest,
  IngestionApiResponse,
  FileDiffItem,
  FileDiffResponse,
  ContentMetadata,
  AuthorMetadata,
} from './ingestion/ingestion.types';
