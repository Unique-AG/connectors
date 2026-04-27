export const SyncStep = {
  ScopeInit: 'scope_init',
  Discovery: 'discovery',
  Diff: 'diff',
  SpaceScopes: 'space_scopes',
  PageIngestion: 'page_ingestion',
  AttachmentIngestion: 'attachment_ingestion',
  Deletion: 'deletion',
  Cleanup: 'cleanup',
  Unknown: 'unknown',
} as const;

export type SyncStep = (typeof SyncStep)[keyof typeof SyncStep];

export type SyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: SyncStep }
  | { status: 'skipped'; reason: string };

export interface SyncRecord {
  timestamp: Date;
  tenantName: string;
  result: SyncResult;
}
