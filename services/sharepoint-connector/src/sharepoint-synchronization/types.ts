import type { SiteConfig } from '../config/tenant-config.schema';

export interface BaseSyncContext {
  // ID of the current user/service account performing operations
  serviceUserId: string;
  // The configured root scope ID for ingestion
  rootScopeId: string;
  // Resolved path of the root scope (e.g. "/Root/Project")
  rootPath: string;
}

export interface SharepointSyncContext extends BaseSyncContext, SiteConfig {
  // SharePoint Site Name being processed
  siteName: string;
}
