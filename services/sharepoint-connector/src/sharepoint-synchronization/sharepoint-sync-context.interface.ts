import type { SiteConfig } from '../config/sharepoint.schema';
import type { ManagedPath } from '../utils/paths.util';
import type { Smeared } from '../utils/smeared';
import type { DiscoveredSubsite } from './subsite-discovery.service';

export interface SharepointSyncContext {
  siteConfig: SiteConfig;
  siteName: Smeared;
  managedPath: ManagedPath;
  serviceUserId: string;
  // Resolved path of the root scope (e.g. "/Root/Project")
  rootPath: Smeared;
  // Resolved root scope ID - for `fixed` rows this is the configured scope; for `auto` rows
  // it's the result of resolution
  rootScopeId: string;
  isInitialSync: boolean;
  discoveredSubsites: DiscoveredSubsite[];
}
