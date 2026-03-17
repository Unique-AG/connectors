import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MessageEventDto } from '../../mail-ingestion/dtos/message-event.dto';
import {
  FullSyncGraphMessage,
  FullSyncGraphMessageFields,
  fullSyncGraphMessageResponseSchema,
} from '../../mail-ingestion/dtos/microsoft-graph.dtos';
import { IngestionPriority } from '../../mail-ingestion/utils/ingestion-queue.utils';
import { sqlArray } from '~/utils/sql-array';

@Injectable()
export class LiveCatchUpCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqp: AmqpConnection,
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

    const { watermark } = lockResult;

    try {
      const { totalScheduled, scheduledIds } = await this.fetchAndScheduleBatches({
        userProfileId,
        subscriptionId,
        watermark,
      });

      const flushedCount = await this.flushPendingMessages({
        userProfileId,
        subscriptionId,
        alreadyScheduledIds: scheduledIds,
      });

      this.logger.log({
        userProfileId,
        subscriptionId,
        totalScheduled: totalScheduled + flushedCount,
        fromBatches: totalScheduled,
        fromPendingFlush: flushedCount,
        msg: 'Live catch-up completed',
      });
    } catch (error) {
      this.logger.error({
        err: error,
        msg: 'Failed to execute live catch-up',
        userProfileId,
        subscriptionId,
      });
      await this.db
        .update(inboxConfiguration)
        .set({ liveCatchUpState: 'failed' })
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();
    }
  }

  private async acquireLock(
    userProfileId: string,
    messageIds: string[],
  ): Promise<{ status: 'proceed'; watermark: Date } | { status: 'skip' }> {
    return this.db.transaction(async (tx) => {
      const inboxConfig = await tx
        .select({
          liveCatchUpState: inboxConfiguration.liveCatchUpState,
          newestLastModifiedDateTime: inboxConfiguration.newestLastModifiedDateTime,
        })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
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
          .update(inboxConfiguration)
          .set({
            pendingLiveMessageIds: sql`array_cat(${inboxConfiguration.pendingLiveMessageIds}, ${sqlArray(messageIds)})`,
          })
          .where(eq(inboxConfiguration.userProfileId, userProfileId))
          .execute();
      };

      if (inboxConfig.liveCatchUpState === 'running') {
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
        .update(inboxConfiguration)
        .set({
          ...(messageIds.length > 0
            ? {
                pendingLiveMessageIds: sql`array_cat(${inboxConfiguration.pendingLiveMessageIds}, ${sqlArray(messageIds)})`,
              }
            : {}),
          liveCatchUpState: 'running',
          liveCatchUpHeartbeatAt: sql`NOW()`,
        })
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      return {
        status: 'proceed',
        watermark: inboxConfig.newestLastModifiedDateTime,
      };
    });
  }

  private async fetchAndScheduleBatches({
    userProfileId,
    subscriptionId,
    watermark,
  }: {
    userProfileId: string;
    subscriptionId: string;
    watermark: Date;
  }): Promise<{ totalScheduled: number; scheduledIds: Set<string> }> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    let totalScheduled = 0;
    const scheduledIds = new Set<string>();
    let batchNumber = 0;

    let emailsRaw = await client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(FullSyncGraphMessageFields)
      // We cannot combine a createdDateTime filter with orderby on lastModifiedDateTime on the
      // Microsoft side (InefficientFilter). The ignoredBefore check is applied in-memory below.
      .filter(`lastModifiedDateTime ge ${watermark.toISOString()}`)
      .orderby('lastModifiedDateTime asc')
      .top(200)
      .get();
    let emailResponse = fullSyncGraphMessageResponseSchema.parse(emailsRaw);

    while (true) {
      batchNumber++;
      const batch = emailResponse.value;

      if (batch.length === 0) {
        break;
      }

      const batchScheduledIds = await this.publishBatch({
        batch,
        subscriptionId,
      });
      for (const id of batchScheduledIds) {
        scheduledIds.add(id);
      }
      totalScheduled += batchScheduledIds.length;

      this.logger.log({
        userProfileId,
        batchNumber,
        batchSize: batch.length,
        scheduled: batchScheduledIds.length,
        totalScheduled,
        msg: 'Batch processed',
      });

      await this.updateWatermarks({ batch, userProfileId });

      if (!emailResponse['@odata.nextLink']) {
        break;
      }

      emailsRaw = await client
        .api(emailResponse['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      emailResponse = fullSyncGraphMessageResponseSchema.parse(emailsRaw);
    }

    traceEvent('live catch-up batches completed', {
      totalScheduled,
      batchCount: batchNumber,
    });

    return { totalScheduled, scheduledIds };
  }

  private async publishBatch({
    batch,
    subscriptionId,
  }: {
    batch: FullSyncGraphMessage[];
    subscriptionId: string;
  }): Promise<string[]> {
    const publishedIds: string[] = [];
    let publishedEvents = 0;

    for (const email of batch) {
      publishedEvents++;
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-event.live-change-notification-received',
        payload: { subscriptionId, messageId: email.id },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.High,
      });
      publishedIds.push(email.id);
    }

    this.logger.debug({
      subscriptionId,
      msg: `PublishBatch - Published Messages: ${publishedEvents}`,
    });

    return publishedIds;
  }

  private async publishMessages({
    messageIds,
    subscriptionId,
  }: {
    messageIds: string[];
    subscriptionId: string;
  }): Promise<number> {
    for (const messageId of messageIds) {
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-event.live-change-notification-received',
        payload: { subscriptionId, messageId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.High,
      });
    }

    return messageIds.length;
  }

  private async flushPendingMessages({
    userProfileId,
    subscriptionId,
    alreadyScheduledIds,
  }: {
    userProfileId: string;
    subscriptionId: string;
    alreadyScheduledIds: Set<string>;
  }): Promise<number> {
    return await this.db.transaction(async (tx) => {
      const row = await tx
        .select({ pendingLiveMessageIds: inboxConfiguration.pendingLiveMessageIds })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!row) {
        return 0;
      }

      const idsToFlush = row.pendingLiveMessageIds.filter((id) => !alreadyScheduledIds.has(id));

      await tx
        .update(inboxConfiguration)
        .set({ pendingLiveMessageIds: [], liveCatchUpState: 'ready' })
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      if (idsToFlush.length > 0) {
        this.logger.debug({
          msg: `Flushing buffered messages while running: ${idsToFlush.length}`,
        });
        await this.publishMessages({ messageIds: idsToFlush, subscriptionId });
      } else {
        this.logger.debug({ msg: `No messages to flush buffered messages is empty` });
      }

      return idsToFlush.length;
    });
  }

  private async updateWatermarks({
    batch,
    userProfileId,
  }: {
    batch: FullSyncGraphMessage[];
    userProfileId: string;
  }): Promise<void> {
    const createdDates = batch.map((e) => new Date(e.createdDateTime));
    const modifiedDates = batch.map((e) => new Date(e.lastModifiedDateTime));

    const batchNewestCreated = new Date(Math.max(...createdDates.map((d) => d.getTime())));
    const batchNewestModified = new Date(Math.max(...modifiedDates.map((d) => d.getTime())));

    await this.db
      .update(inboxConfiguration)
      .set({
        newestCreatedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestCreatedDateTime}, '-infinity'::timestamptz), ${batchNewestCreated})`,
        newestLastModifiedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestLastModifiedDateTime}, '-infinity'::timestamptz), ${batchNewestModified})`,
        liveCatchUpHeartbeatAt: sql`NOW()`,
      })
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .execute();
  }
}
