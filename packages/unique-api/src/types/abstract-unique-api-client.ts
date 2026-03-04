import type { UniqueAuthFacade } from '../auth/unique-auth.facade';
import type { UniqueContentFacade } from '../content/unique-content.facade';
import type { UniqueFilesFacade } from '../files/unique-files.facade';
import type { UniqueGroupsFacade } from '../groups/unique-groups.facade';
import type { UniqueIngestionFacade } from '../ingestion/unique-ingestion.facade';
import type { UniqueApiScopesFacade } from '../scopes/unique-scopes.facade';
import type { UniqueUsersFacade } from '../users/unique-users.facade';
import type { UniqueApiClient } from './unique-api-client.types';

// Abstract class usable as a DI token (interfaces are erased at runtime)
export abstract class AbstractUniqueApiClient implements UniqueApiClient {
  public abstract readonly auth: UniqueAuthFacade;
  public abstract readonly scopes: UniqueApiScopesFacade;
  public abstract readonly files: UniqueFilesFacade;
  public abstract readonly users: UniqueUsersFacade;
  public abstract readonly groups: UniqueGroupsFacade;
  public abstract readonly ingestion: UniqueIngestionFacade;
  public abstract readonly content: UniqueContentFacade;
  public abstract close?(): Promise<void>;
}
