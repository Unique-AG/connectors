import type { SiteConfig } from '../config/sharepoint.schema';

export interface BaseSyncContext {
  // ID of the current user/service account performing operations
  serviceUserId: string;
  // The configured root scope ID for ingestion
  rootScopeId: string;
  // Resolved path of the root scope (e.g. "/Root/Project")
  rootPath: string;
}

export interface SharepointSyncContext extends BaseSyncContext {
  // SharePoint Site ID being processed
  siteId: string;
  // SharePoint Site Name being processed
  siteName: string;
  // Site-specific configuration
  siteConfig: SiteConfig;
}
