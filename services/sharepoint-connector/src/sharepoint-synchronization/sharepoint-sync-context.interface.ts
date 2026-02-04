import type { SiteConfig } from '../config/sharepoint.schema';
import { Smeared } from '../utils/smeared';

export interface SharepointSyncContext {
  siteConfig: SiteConfig;
  siteName: Smeared;
  serviceUserId: string;
  /** Resolved path of the root scope (e.g. "/Root/Project") */
  rootPath: string;
}
