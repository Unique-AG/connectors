import type { SiteConfig } from '../config/sharepoint.schema';
import type { Smeared } from '../utils/smeared';
import type { DiscoveredSubsite } from './subsite-discovery.service';

export interface SharepointSyncContext {
  siteConfig: SiteConfig;
  siteName: Smeared;
  serviceUserId: string;
  /** Resolved path of the root scope (e.g. "/Root/Project") */
  rootPath: Smeared;
  isInitialSync: boolean;
  discoveredSubsites: DiscoveredSubsite[];
}
