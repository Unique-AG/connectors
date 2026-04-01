import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { SyncDirectoriesCommand } from '~/features/directories-sync/sync-directories.command';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { isWithinCooldown } from '~/utils/is-within-cooldown';
import { sqlArray } from '~/utils/sql-array';
import {
  LiveCatchUpGraphMessage,
  LiveCatchUpGraphMessageFields,
  liveCatchUpGraphMessageResponseSchema,
} from '../../mail-ingestion/dtos/microsoft-graph.dtos';
import { IngestEmailCommand } from '../../mail-ingestion/ingest-email.command';

export const RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES = 20;
export const FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES = 5;
export const READY_LIVE_CATCHUP_THRESHOLD_MINUTES = 60 * 4;

@Injectable()
export class LiveCatchUpCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly ingestEmailCommand: IngestEmailCommand,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run({
    subscriptionId,
    messageIds = [],
  }: {
    subscriptionId: string;
    messageIds?: string[];
  }): Promise<void> {
    traceAttrs({ subscriptionId });
    this.logger.log({
      subscriptionId,
      webhookMessageIds: messageIds.length,
      msg: 'Live catch-up triggered',
    });

    const subscription = await this.db.query.subscriptions.findFirst({
      columns: { userProfileId: true },
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });

    if (!subscription) {
      this.logger.warn({ subscriptionId, msg: 'Subscription not found, skipping' });
      return;
    }

    const { userProfileId } = subscription;
    traceAttrs({ userProfileId });

    const lockResult = await this.acquireLock(userProfileId, messageIds);
    if (lockResult.status === 'skip') {
      return;
    }

    const { watermark, filters } = lockResult;

    try {
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfileId));

      const processedIds = await this.processMessages({
        userProfileId,
        watermark,
        filters,
      });

      const flushedCount = await this.flushPendingMessages({
        userProfileId,
        filters,
        alreadyProcessedIds: processedIds,
      });

      this.logger.log({
        userProfileId,
        subscriptionId,
        totalProcessed: processedIds.size + flushedCount,
        fromBatches: processedIds.size,
        fromPendingFlush: flushedCount,
        msg: 'Live catch-up completed',
      });
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'ready', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .execute();
    } catch (error) {
      this.logger.error({
        err: error,
        msg: 'Failed to execute live catch-up',
        userProfileId,
        subscriptionId,
      });
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'failed', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .execute();
    }
  }

  private async acquireLock(
    userProfileId: string,
    messageIds: string[],
  ): Promise<
    | { status: 'proceed'; watermark: Date; filters: InboxConfigurationMailFilters }
    | { status: 'skip' }
  > {
    return this.db.transaction(async (tx) => {
      const inboxConfig = await tx
        .select({
          liveCatchUpState: inboxConfigurations.liveCatchUpState,
          newestLastModifiedDateTime: inboxConfigurations.newestLastModifiedDateTime,
          liveCatchUpHeartbeatAt: inboxConfigurations.liveCatchUpHeartbeatAt,
          filters: inboxConfigurations.filters,
        })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!inboxConfig) {
        this.logger.warn({ userProfileId, msg: 'No inbox configuration found, skipping' });
        return { status: 'skip' };
      }

      // This function is defined here because it needs the transaction context
      const addMessagesToPendingMessages = async (): Promise<void> => {
        if (messageIds.length === 0) {
          return;
        }

        await tx
          .update(inboxConfigurations)
          .set({
            // Note: array_cat -> maintains the order of the array so if we change the function we should ensure ordering
            // because the flushing operation depends on the array to have the same order.
            pendingLiveMessageIds: sql`array_cat(${inboxConfigurations.pendingLiveMessageIds}, ${sqlArray(messageIds)})`,
          })
          .where(eq(inboxConfigurations.userProfileId, userProfileId))
          .execute();
      };

      if (
        inboxConfig.liveCatchUpState === 'running' &&
        isWithinCooldown(inboxConfig.liveCatchUpHeartbeatAt, RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES)
      ) {
        // We buffer the messages because once the process finishes it will flush the messages.
        await addMessagesToPendingMessages();
        this.logger.log({
          userProfileId,
          bufferedCount: messageIds.length,
          msg: `Live catch-up already running, buffered message IDs count: ${messageIds.length}`,
        });
        return { status: 'skip' };
      }

      if (!inboxConfig.newestLastModifiedDateTime) {
        // We buffer the messages to ensure we do not lose any message, and next live update will ensure it included this messages.
        // This case should can only happen if a live update catches the lock before the full sync basically the following case.
        // We subscribe to microsoft + trigger event for full sync.
        // Microsoft triggers live update:
        // Live update catches the lock before full sync catches the lock.
        await addMessagesToPendingMessages();
        this.logger.log({
          userProfileId,
          msg: `No watermark yet (full sync not started), skipping, buffered message IDs count: ${messageIds.length}`,
        });
        return { status: 'skip' };
      }

      await tx
        .update(inboxConfigurations)
        .set({
          ...(messageIds.length > 0
            ? {
                // Note: array_cat -> maintains the order of the array so if we change the function we should ensure ordering
                // because the flushing operation depends on the array to have the same order.
                pendingLiveMessageIds: sql`array_cat(${inboxConfigurations.pendingLiveMessageIds}, ${sqlArray(messageIds)})`,
              }
            : {}),
          liveCatchUpState: 'running',
          liveCatchUpHeartbeatAt: sql`NOW()`,
        })
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .execute();

      const filters = inboxConfigurationMailFilters.parse(inboxConfig.filters);
      return {
        status: 'proceed',
        watermark: inboxConfig.newestLastModifiedDateTime,
        filters,
      };
    });
  }

  private async processMessages({
    userProfileId,
    watermark,
    filters,
  }: {
    userProfileId: string;
    watermark: Date;
    filters: InboxConfigurationMailFilters;
  }): Promise<Set<string>> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const processedIds = new Set<string>();
    let batchNumber = 0;

    let emailsRaw = await client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(LiveCatchUpGraphMessageFields)
      // We cannot combine a createdDateTime filter with orderby on lastModifiedDateTime on the
      // Microsoft side (InefficientFilter). The ignoredBefore check is applied in-memory below.
      .filter(`lastModifiedDateTime ge ${watermark.toISOString()}`)
      .orderby('lastModifiedDateTime asc')
      .top(200)
      .get();
    let emailResponse = liveCatchUpGraphMessageResponseSchema.parse(emailsRaw);

    while (true) {
      batchNumber++;
      const batch = emailResponse.value;

      if (batch.length === 0) {
        break;
      }

      for (const email of batch) {
        const result = await this.ingestEmailCommand.run({
          userProfileId,
          messageId: email.id,
          filters,
        });

        if (result === 'failed') {
          this.logger.warn({
            userProfileId,
            messageId: email.id,
            msg: 'Email ingestion failed, continuing',
          });
        }

        await this.updateWatermarks({ email, userProfileId });
        processedIds.add(email.id);
      }

      this.logger.log({
        userProfileId,
        batchNumber,
        batchSize: batch.length,
        msg: 'Batch processed',
      });

      if (!emailResponse['@odata.nextLink']) {
        break;
      }

      emailsRaw = await client
        .api(emailResponse['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      emailResponse = liveCatchUpGraphMessageResponseSchema.parse(emailsRaw);
    }

    traceEvent('live catch-up batches completed', {
      processedCount: processedIds.size,
      batchCount: batchNumber,
    });

    return processedIds;
  }

  private async flushPendingMessages({
    userProfileId,
    filters,
    alreadyProcessedIds,
  }: {
    userProfileId: string;
    filters: InboxConfigurationMailFilters;
    alreadyProcessedIds: Set<string>;
  }): Promise<number> {
    const idsToFlush = await this.db
      .select({ pendingLiveMessageIds: inboxConfigurations.pendingLiveMessageIds })
      .from(inboxConfigurations)
      .where(eq(inboxConfigurations.userProfileId, userProfileId))
      .then((rows) => rows?.[0]?.pendingLiveMessageIds ?? []);

    if (idsToFlush.length === 0) {
      return 0;
    }

    this.logger.debug({
      msg: `Flushing buffered messages while running: ${idsToFlush.length}`,
    });

    let index = 0;

    try {
      for (; index < idsToFlush.length; index++) {
        const messageId = idsToFlush[index];
        if (!messageId || alreadyProcessedIds.has(messageId)) {
          continue;
        }
        const result = await this.ingestEmailCommand.run({ userProfileId, messageId, filters });
        if (result === 'failed') {
          this.logger.warn({
            userProfileId,
            messageId,
            msg: 'Email ingestion failed during flush, continuing',
          });
        }
      }
    } finally {
      // We do this on finally because we want to cleanup what we processed if this.ingestEmailCommand.run throws.
      // index is the JS 0-based position of the element that threw (or idsToFlush.length on normal completion).
      // PG arrays are 1-indexed, so arr[index+1:] drops the first `index` elements and keeps the rest.
      await this.db
        .update(inboxConfigurations)
        .set({
          pendingLiveMessageIds: sql`${inboxConfigurations.pendingLiveMessageIds}[${index + 1}:]`,
        })
        .where(eq(inboxConfigurations.userProfileId, userProfileId));
    }

    return idsToFlush.length;
  }

  private async updateWatermarks({
    email,
    userProfileId,
  }: {
    email: LiveCatchUpGraphMessage;
    userProfileId: string;
  }): Promise<void> {
    const createdDate = new Date(email.createdDateTime);
    const modifiedDate = new Date(email.lastModifiedDateTime);

    await this.db
      .update(inboxConfigurations)
      .set({
        newestCreatedDateTime: sql`GREATEST(COALESCE(${inboxConfigurations.newestCreatedDateTime}, '-infinity'::timestamptz), ${createdDate})`,
        newestLastModifiedDateTime: sql`GREATEST(COALESCE(${inboxConfigurations.newestLastModifiedDateTime}, '-infinity'::timestamptz), ${modifiedDate})`,
        liveCatchUpHeartbeatAt: sql`NOW()`,
      })
      .where(eq(inboxConfigurations.userProfileId, userProfileId))
      .execute();
  }
}
