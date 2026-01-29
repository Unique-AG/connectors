import type { SiteConfig } from '../../src/config/sharepoint.schema';
import { IngestionMode } from '../../src/constants/ingestion.constants';
import { StoreInternallyMode } from '../../src/constants/store-internally-mode.enum';

export const createMockSiteConfig = (overrides?: Partial<SiteConfig>): SiteConfig => ({
  siteId: 'site-id',
  syncColumnName: 'TestColumn',
  ingestionMode: IngestionMode.Flat,
  scopeId: 'scope-id',
  maxFilesToIngest: 1000,
  storeInternally: StoreInternallyMode.Enabled,
  syncStatus: 'active',
  syncMode: 'content_only',
  permissionsInheritanceMode: 'inherit_scopes_and_files',
  ...overrides,
});
