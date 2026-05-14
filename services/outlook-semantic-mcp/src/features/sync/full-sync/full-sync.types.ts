export type FullSyncResult =
  | { status: 'skipped'; reason: string }
  | { status: 'waiting-for-ingestion' }
  | { status: 'completed' }
  | { status: 'failed'; error: unknown };
