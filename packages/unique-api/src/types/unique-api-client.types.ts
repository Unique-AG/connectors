import type { UniqueAuthFacade } from '../auth/unique-auth.facade';
import type { UniqueFilesFacade } from '../files/unique-files.facade';
import type { UniqueGroupsFacade } from '../groups/unique-groups.facade';
import type { UniqueIngestionFacade } from '../ingestion/unique-ingestion.facade';
import type { UniqueApiScopes } from '../scopes/unique-scopes.facade';
import type { UniqueUsersFacade } from '../users/unique-users.facade';

export interface UniqueApiClient {
  auth: UniqueAuthFacade;
  scopes: UniqueApiScopes;
  files: UniqueFilesFacade;
  users: UniqueUsersFacade;
  groups: UniqueGroupsFacade;
  ingestion: UniqueIngestionFacade;
  close?(): Promise<void>;
}
