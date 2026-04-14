import type { FullSyncStep, SiteSyncStep } from '../constants/sync-step.enum';

export type SyncResult<TStep extends string = string> =
  | { status: 'success' }
  | { status: 'failure'; step: TStep }
  | { status: 'skipped'; reason: string };

export type FullSyncResult = SyncResult<FullSyncStep>;
export type SiteSyncResult = SyncResult<SiteSyncStep>;

export interface SiteResultEntry {
  siteId: string;
  result: SiteSyncResult;
}

export interface SyncRecord {
  timestamp: Date;
  fullResult: FullSyncResult;
  siteResults: SiteResultEntry[];
}
