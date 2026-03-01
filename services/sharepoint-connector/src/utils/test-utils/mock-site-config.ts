import type { SiteConfig } from '../../config/sharepoint.schema';
import { EnabledDisabledMode } from '../../constants/enabled-disabled-mode.enum';
import { IngestionMode } from '../../constants/ingestion.constants';
import { createSmeared } from '../smeared';

export const createMockSiteConfig = (overrides?: Partial<SiteConfig>): SiteConfig => ({
  siteId: createSmeared('site-id'),
  syncColumnName: 'TestColumn',
  ingestionMode: IngestionMode.Flat,
  scopeId: 'scope-id',
  maxFilesToIngest: 1000,
  storeInternally: EnabledDisabledMode.Enabled,
  syncStatus: 'active',
  syncMode: 'content_only',
  permissionsInheritanceMode: 'inherit_scopes_and_files',
  subsitesScan: EnabledDisabledMode.Disabled,
  ...overrides,
});
