import type { UniqueAuthFacade } from '../auth/unique-auth.facade';
import type { UniqueContentFacade } from '../content/unique-content.facade';
import type { UniqueFilesFacade } from '../files/unique-files.facade';
import type { UniqueGroupsFacade } from '../groups/unique-groups.facade';
import type { UniqueIngestionFacade } from '../ingestion/unique-ingestion.facade';
import type { UniqueApiScopesFacade } from '../scopes/unique-scopes.facade';
import type { UniqueUsersFacade } from '../users/unique-users.facade';

export interface UniqueApiClient {
  auth: UniqueAuthFacade;
  scopes: UniqueApiScopesFacade;
  files: UniqueFilesFacade;
  users: UniqueUsersFacade;
  groups: UniqueGroupsFacade;
  ingestion: UniqueIngestionFacade;
  content: UniqueContentFacade;
  close?(): Promise<void>;
}
