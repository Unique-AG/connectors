import type { SiteConfig } from '../config/tenant-config.schema';

export interface SharepointSyncContext {
  /** The configuration for the SharePoint site being processed */
  config: SiteConfig;
  /** SharePoint Site Name being processed */
  siteName: string;
  /** ID of the current user/service account performing operations */
  serviceUserId: string;
  /** Resolved path of the root scope (e.g. "/Root/Project") */
  rootPath: string;
}
