import crypto from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { SyncDirectoriesCommand } from '~/features/directories-sync/sync-directories.command';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GetScopeIngestionStatsQuery } from './get-scope-ingestion-stats.query';
import { ProcessFullSyncBatchCommand } from './process-full-sync-batch.command';
import { UpdateInboxConfigByVersionCommand } from './update-inbox-config-by-version.command';

type InboxConfig = typeof inboxConfiguration.$inferSelect;

export const START_FULL_SYNC_LINK = 'SYNC_STARTED:__EMPTY_DELTA__';

const READY_COOLDOWN_MINUTES = 5;
export const STALE_HEARTBEAT_MINUTES = 20;
export const WAITING_FOR_INGESTION_HEARTBEAT_MINUTES = 5;
export const WAITING_FOR_FAILED_HEARTBEAT_MINUTES = 20;
const MAX_ON_GOING_INGESTION_IN_PROGRESS = 10;

export type FullSyncResult =
  | { status: 'skipped'; reason: string }
  | { status: 'waiting-for-ingestion' }
  | { status: 'completed' }
  | { status: 'failed'; error: unknown };

@Injectable()
export class FullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly processFullSyncBatchCommand: ProcessFullSyncBatchCommand,
    private readonly getScopeIngestionStatsQuery: GetScopeIngestionStatsQuery,
    private readonly updateByVersionCommand: UpdateInboxConfigByVersionCommand,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<FullSyncResult> {
    traceAttrs({ userProfileId });
    this.logger.log({ userProfileId, msg: 'Full sync triggered' });

    const lockResult = await this.acquireLockAndDecide(userProfileId);

    if (lockResult.action === 'skip') {
      traceEvent('full sync skipped', { reason: lockResult.reason });
      this.logger.log({ userProfileId, reason: lockResult.reason, msg: 'Full sync skipped' });
      return { status: 'skipped', reason: lockResult.reason };
    }

    const { version, previousState } = lockResult;

    // If the previousState was 'running' we should also check the scope to see if ingestion queue
    // is still in progress because we try to recover syncs which are stalling in 'running' status
    // and we will push them through the queue then here we should check what happens in our scope.
    if (['waiting-for-ingestion', 'running'].includes(previousState)) {
      const ingestionVerificationResult = await this.verifyIngestionStatus({
        userProfileId,
        version,
      });

      if (ingestionVerificationResult.status !== 'proceed') {
        return ingestionVerificationResult;
      }
    }

    try {
      if (lockResult.shouldFetchCount) {
        await this.fetchAndSaveExpectedTotal(userProfileId, version);
      }
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfileId));

      const batchResult = await this.processFullSyncBatchCommand.run({
        userProfileId,
        version,
      });

      switch (batchResult.outcome) {
        case 'version-mismatch':
        case 'missing-full-sync-next-link':
          this.logger.log({ userProfileId, version, msg: `Exiting: ${batchResult.outcome}` });
          return { status: 'skipped', reason: 'version-mismatch' };

        case 'batch-uploaded': {
          const newStateSaved = await this.transitionState(
            userProfileId,
            version,
            'waiting-for-ingestion',
          );
          if (!newStateSaved) {
            this.logger.warn({
              userProfileId,
              version,
              msg: 'Version mismatch after batch upload',
            });
            return { status: 'skipped', reason: 'version-mismatch' };
          }
          this.logger.log({ userProfileId, version, msg: 'Batch uploaded, waiting for ingestion' });
          return { status: 'waiting-for-ingestion' };
        }

        case 'completed': {
          const updated = await this.updateByVersionCommand.run(userProfileId, version, {
            fullSyncState: 'ready',
            fullSyncLastRunAt: new Date(),
            fullSyncNextLink: null,
            fullSyncBatchIndex: 0,
            fullSyncHeartbeatAt: sql`NOW()`,
          });
          if (!updated) {
            this.logger.warn({
              userProfileId,
              version,
              msg: 'Version mismatch on completion update',
            });
            return { status: 'skipped', reason: 'version-mismatch' };
          }
          this.logger.log({ userProfileId, version, msg: 'Full sync completed' });
          return { status: 'completed' };
        }

        default: {
          throw new Error(`Unhandled batch result: ${JSON.stringify(batchResult)}`);
        }
      }
    } catch (error) {
      this.logger.error({ err: error, userProfileId, version, msg: 'Full sync failed' });
      await this.transitionState(userProfileId, version, 'failed');
      return { status: 'failed', error };
    }
  }

  private async acquireLockAndDecide(userProfileId: string): Promise<LockDecision> {
    return this.db.transaction(async (tx) => {
      const row = await tx
        .select({
          fullSyncState: inboxConfiguration.fullSyncState,
          fullSyncVersion: inboxConfiguration.fullSyncVersion,
          fullSyncNextLink: inboxConfiguration.fullSyncNextLink,
          fullSyncHeartbeatAt: inboxConfiguration.fullSyncHeartbeatAt,
          fullSyncLastRunAt: inboxConfiguration.fullSyncLastRunAt,
          fullSyncExpectedTotal: inboxConfiguration.fullSyncExpectedTotal,
          newestLastModifiedDateTime: inboxConfiguration.newestLastModifiedDateTime,
        })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!row) {
        return { action: 'skip' as const, reason: 'no-inbox-configuration' };
      }

      const decision = this.decideAction(row);
      if (decision.action === 'skip') {
        return decision;
      }

      const previousState = row.fullSyncState;
      const version = crypto.randomUUID();
      const now = new Date();
      const isFreshStart = isNullish(row.fullSyncNextLink);

      const updateSet: Partial<typeof inboxConfiguration.$inferInsert> = {
        fullSyncState: 'running',
        fullSyncVersion: version,
        fullSyncHeartbeatAt: now,
      };

      if (isFreshStart) {
        updateSet.fullSyncLastStartedAt = now;
        updateSet.fullSyncNextLink = START_FULL_SYNC_LINK;
        updateSet.fullSyncBatchIndex = 0;
        updateSet.fullSyncSkipped = 0;
        updateSet.fullSyncScheduledForIngestion = 0;
        updateSet.fullSyncFailedToUploadForIngestion = 0;
        updateSet.fullSyncExpectedTotal = null;
        updateSet.oldestCreatedDateTime = null;
        updateSet.newestLastModifiedDateTime = row.newestLastModifiedDateTime ?? now;
      }

      await tx
        .update(inboxConfiguration)
        .set(updateSet)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      return {
        action: 'proceed' as const,
        version,
        previousState,
        shouldFetchCount: isFreshStart || isNullish(row.fullSyncExpectedTotal),
      };
    });
  }

  private decideAction(
    row: Pick<
      InboxConfig,
      | 'fullSyncState'
      | 'fullSyncVersion'
      | 'fullSyncNextLink'
      | 'fullSyncHeartbeatAt'
      | 'fullSyncLastRunAt'
      | 'fullSyncExpectedTotal'
    >,
  ): { action: 'skip'; reason: string } | { action: 'proceed' } {
    switch (row.fullSyncState) {
      case 'ready':
        if (this.isWithinCooldown(row.fullSyncLastRunAt, READY_COOLDOWN_MINUTES)) {
          return { action: 'skip', reason: 'ran-recently' };
        }
        return { action: 'proceed' };
      case 'waiting-for-ingestion':
        return { action: 'proceed' };
      case 'running':
        if (this.isWithinCooldown(row.fullSyncHeartbeatAt, STALE_HEARTBEAT_MINUTES)) {
          return { action: 'skip', reason: 'already-running' };
        }
        this.logger.warn({ msg: 'Recovering stale running sync (heartbeat too old)' });
        return { action: 'proceed' };
      case 'failed':
        if (this.isWithinCooldown(row.fullSyncHeartbeatAt, WAITING_FOR_FAILED_HEARTBEAT_MINUTES)) {
          return { action: 'skip', reason: 'already-running' };
        }
        return { action: 'proceed' };
      case 'paused':
        return { action: 'skip', reason: 'paused' };
    }
  }

  private isWithinCooldown(timestamp: Date | null, cooldownMinutes: number): boolean {
    if (isNullish(timestamp)) {
      return false;
    }
    const cooldownThreshold = new Date();
    cooldownThreshold.setMinutes(cooldownThreshold.getMinutes() - cooldownMinutes);
    return timestamp > cooldownThreshold;
  }

  private async fetchAndSaveExpectedTotal(userProfileId: string, version: string): Promise<void> {
    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);
      const count = (await client
        .api('me/messages/$count')
        .header('Prefer', 'IdType="ImmutableId"')
        .header('ConsistencyLevel', 'eventual')
        .get()) as number;

      await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncExpectedTotal: count,
        fullSyncHeartbeatAt: sql`NOW()`,
      });

      this.logger.log({ userProfileId, expectedTotal: count, msg: 'Expected total fetched' });
    } catch (error) {
      this.logger.warn({
        err: error,
        userProfileId,
        msg: 'Failed to fetch $count, proceeding without expectedTotal',
      });
    }
  }

  private async verifyIngestionStatus({
    userProfileId,
    version,
  }: {
    userProfileId: string;
    version: string;
  }): Promise<
    | { status: 'proceed' }
    | { status: 'skipped'; reason: 'version-mismatch' }
    | { status: 'waiting-for-ingestion' }
  > {
    const result = await this.getScopeIngestionStatsQuery.run(userProfileId);
    if (result.ok && result.inProgress < MAX_ON_GOING_INGESTION_IN_PROGRESS) {
      return { status: 'proceed' };
    }

    if (!result.ok) {
      this.logger.log({ userProfileId, version, msg: 'Ingestion is not reachable, waiting again' });
    } else {
      this.logger.log({ userProfileId, version, msg: 'Scope still draining, waiting again' });
    }
    const isSaved = await this.transitionState(userProfileId, version, 'waiting-for-ingestion');
    if (!isSaved) {
      this.logger.log({ userProfileId, version, msg: 'Skipping state transition failed' });
      return { status: 'skipped', reason: 'version-mismatch' };
    }

    return { status: 'waiting-for-ingestion' };
  }

  private async transitionState(
    userProfileId: string,
    version: string,
    state: InboxConfig['fullSyncState'],
  ): Promise<boolean> {
    return this.updateByVersionCommand.run(userProfileId, version, {
      fullSyncState: state,
      fullSyncHeartbeatAt: sql`NOW()`,
    });
  }
}

type LockDecision =
  | { action: 'skip'; reason: string }
  | {
      action: 'proceed';
      version: string;
      previousState: InboxConfig['fullSyncState'];
      shouldFetchCount: boolean;
    };
