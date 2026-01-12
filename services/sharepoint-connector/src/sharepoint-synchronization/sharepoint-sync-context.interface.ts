import type { SiteConfig } from '../config/tenant-config.schema';

export interface SharepointSyncContext {
  siteConfig: SiteConfig;
  siteName: string;
  serviceUserId: string;
  /** Resolved path of the root scope (e.g. "/Root/Project") */
  rootPath: string;
}
