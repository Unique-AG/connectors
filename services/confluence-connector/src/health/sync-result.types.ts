export type SyncResult =
  | { status: 'success' }
  | { status: 'failure' }
  | { status: 'skipped'; reason: string };

export interface SyncRecord {
  timestamp: Date;
  tenantName: string;
  result: SyncResult;
}
