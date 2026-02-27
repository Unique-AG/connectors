import type { UniqueApiScopes } from '@unique-ag/unique-api';
import type { UniqueFilesFacade } from './files.types';
import type { UniqueIngestionFacade } from './ingestion.types';

// Abstract class used as a service token (interfaces are erased at runtime and cannot be used as ServiceRegistry keys)
export abstract class UniqueApiClient {
  public abstract readonly auth: unknown;
  public abstract readonly scopes: UniqueApiScopes;
  public abstract readonly files: UniqueFilesFacade;
  public abstract readonly users: unknown;
  public abstract readonly groups: unknown;
  public abstract readonly ingestion: UniqueIngestionFacade;
  public async close(): Promise<void> {}
}
