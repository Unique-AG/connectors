import { inboxConfigurations } from '~/db';

export type FullSyncResult =
  | { status: 'skipped'; reason: string }
  | { status: 'waiting-for-ingestion' }
  | { status: 'completed' }
  | { status: 'failed'; error: unknown };

export type InboxConfig = typeof inboxConfigurations.$inferSelect;

export type LockDecision =
  | { action: 'skip'; reason: string }
  | {
      action: 'proceed';
      version: string;
      previousState: InboxConfig['fullSyncState'];
      shouldFetchCount: boolean;
      filters: Record<string, unknown>;
      preferredDelegateUserProfileId: string | null;
    };

export type BatchResult =
  | { outcome: 'batch-uploaded' }
  | { outcome: 'completed' }
  | { outcome: 'version-mismatch' }
  | { outcome: 'missing-full-sync-next-link' };
