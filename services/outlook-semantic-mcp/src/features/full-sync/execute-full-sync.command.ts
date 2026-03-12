import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, SQL, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '../../db/schema/inbox/inbox-configuration-mail-filters.dto';
import { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { MessageEventDto } from '../mail-ingestion/dtos/message-event.dto';
import {
  FullSyncGraphMessage,
  FullSyncGraphMessageFields,
  fullSyncGraphMessageResponseSchema,
} from '../mail-ingestion/dtos/microsoft-graph.dtos';
import { IngestionPriority } from '../mail-ingestion/utils/ingestion-queue.utils';
import { shouldSkipEmail } from '../mail-ingestion/utils/should-skip-email';

type InboxConfiguration = typeof inboxConfiguration.$inferSelect;

@Injectable()
export class ExecuteFullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqp: AmqpConnection,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run({
    userProfileId,
    version,
  }: {
    userProfileId: string;
    version: string;
  }): Promise<void> {
    traceAttrs({ userProfileId, version });
    this.logger.log({ userProfileId, version, msg: 'Received full sync execute event' });

    const inboxConfig = await this.db
      .select({
        fullSyncState: inboxConfiguration.fullSyncState,
        fullSyncVersion: inboxConfiguration.fullSyncVersion,
        filters: inboxConfiguration.filters,
        oldestLastModifiedDateTime: inboxConfiguration.oldestLastModifiedDateTime,
        fullSyncNextLink: inboxConfiguration.fullSyncNextLink,
      })
      .from(inboxConfiguration)
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .then((rows) => rows[0]);

    if (!inboxConfig) {
      this.logger.warn({ userProfileId, version, msg: 'No inbox configuration found, discarding' });
      return;
    }

    if (
      inboxConfig.fullSyncVersion !== version ||
      inboxConfig.fullSyncState !== 'fetching-emails'
    ) {
      this.logger.log({
        userProfileId,
        version,
        currentVersion: inboxConfig.fullSyncVersion,
        currentState: inboxConfig.fullSyncState,
        msg: 'Stale execute event, discarding',
      });
      return;
    }

    const isResume = isNonNullish(inboxConfig.oldestLastModifiedDateTime);
    const filters = inboxConfigurationMailFilters.parse(inboxConfig.filters);

    try {
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfileId));

      this.logger.log({
        userProfileId,
        version,
        ignoredBefore: filters.ignoredBefore,
        isResume,
        msg: 'Fetching emails in batches',
      });

      await this.fetchAndScheduleBatches({
        userProfileId,
        filters,
        version,
        isResume,
        oldestLastModifiedDateTime: inboxConfig.oldestLastModifiedDateTime,
        nextLink: inboxConfig.fullSyncNextLink,
      });

      await this.updateInboxConfigByVersion(userProfileId, version, {
        fullSyncState: 'ready',
        lastFullSyncRunAt: new Date(),
        fullSyncNextLink: null,
      });

      this.logger.log({ userProfileId, version, msg: 'Full sync completed' });
    } catch (error) {
      this.logger.error({
        err: error,
        msg: 'Failed to execute full sync',
        userProfileId,
        version,
      });
      await this.updateInboxConfigByVersion(userProfileId, version, {
        fullSyncState: 'failed',
      });
    }
  }

  private async fetchAndScheduleBatches({
    userProfileId,
    filters,
    version,
    isResume,
    oldestLastModifiedDateTime,
    nextLink,
  }: {
    userProfileId: string;
    filters: InboxConfigurationMailFilters;
    version: string;
    isResume: boolean;
    oldestLastModifiedDateTime: Date | null;
    nextLink: string | null;
  }): Promise<void> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    let totalScheduled = 0;
    let batchNumber = 0;

    let emailsRaw: unknown;

    if (nextLink) {
      try {
        emailsRaw = await client.api(nextLink).header('Prefer', 'IdType="ImmutableId"').get();
      } catch (error) {
        this.logger.warn({
          err: error,
          userProfileId,
          msg: 'Next link fetch failed, clearing and falling back to fresh fetch',
        });

        await this.updateInboxConfigByVersion(userProfileId, version, {
          fullSyncNextLink: null,
        });

        nextLink = null;
      }
    }

    if (!nextLink) {
      let filterExpression = `createdDateTime gt ${filters.ignoredBefore.toISOString()}`;
      if (isResume && oldestLastModifiedDateTime) {
        filterExpression += ` and lastModifiedDateTime lte ${oldestLastModifiedDateTime.toISOString()}`;
      }

      emailsRaw = await client
        .api(`me/messages`)
        .header('Prefer', 'IdType="ImmutableId"')
        .select(FullSyncGraphMessageFields)
        .filter(filterExpression)
        .orderby(`lastModifiedDateTime desc`)
        .top(200)
        .get();
    }

    let emailResponse = fullSyncGraphMessageResponseSchema.parse(emailsRaw);

    while (true) {
      batchNumber++;
      const batch = emailResponse.value;

      if (batch.length === 0) {
        break;
      }

      const scheduled = await this.processBatch({
        batch,
        filters,
        userProfileId,
        version,
      });
      totalScheduled += scheduled;

      this.logger.log({
        userProfileId,
        batchNumber,
        batchSize: batch.length,
        scheduled,
        totalScheduled,
        msg: `Batch processed`,
      });

      const versionStillValid = await this.updateWatermarks({
        batch,
        userProfileId,
        version,
      });

      if (!versionStillValid) {
        this.logger.log({
          userProfileId,
          msg: `Sync cancelled — version mismatch`,
        });
        return;
      }

      const currentNextLink = emailResponse['@odata.nextLink'] ?? null;

      await this.updateInboxConfigByVersion(userProfileId, version, {
        fullSyncNextLink: currentNextLink,
      });

      if (!currentNextLink) {
        break;
      }

      emailsRaw = await client.api(currentNextLink).header('Prefer', 'IdType="ImmutableId"').get();
      emailResponse = fullSyncGraphMessageResponseSchema.parse(emailsRaw);
    }

    traceEvent('full sync batches completed', {
      totalScheduled,
      batchCount: batchNumber,
    });
    this.logger.log({
      userProfileId,
      totalScheduled,
      batchCount: batchNumber,
      msg: `All batches processed`,
    });
  }

  private async processBatch({
    batch,
    filters,
    userProfileId,
    version,
  }: {
    batch: FullSyncGraphMessage[];
    filters: InboxConfigurationMailFilters;
    userProfileId: string;
    version: string;
  }): Promise<number> {
    let scheduled = 0;

    for (const email of batch) {
      const skipResult = shouldSkipEmail(email, filters, { userProfileId });
      if (skipResult.skip) {
        continue;
      }

      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled',
        payload: { messageId: email.id, userProfileId, fullSyncVersion: version },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.Low,
      });
      scheduled++;
    }

    return scheduled;
  }

  private async updateWatermarks({
    batch,
    userProfileId,
    version,
  }: {
    batch: FullSyncGraphMessage[];
    userProfileId: string;
    version: string;
  }): Promise<boolean> {
    const createdDates = batch.map((e) => new Date(e.createdDateTime));
    const modifiedDates = batch.map((e) => new Date(e.lastModifiedDateTime));

    const batchNewestCreated = new Date(Math.max(...createdDates.map((d) => d.getTime())));
    const batchOldestCreated = new Date(Math.min(...createdDates.map((d) => d.getTime())));
    const batchNewestModified = new Date(Math.max(...modifiedDates.map((d) => d.getTime())));
    const batchOldestModified = new Date(Math.min(...modifiedDates.map((d) => d.getTime())));

    return await this.updateInboxConfigByVersion(userProfileId, version, {
      newestCreatedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestCreatedDateTime}, '-infinity'::timestamptz), ${batchNewestCreated})`,
      oldestCreatedDateTime: sql`LEAST(COALESCE(${inboxConfiguration.oldestCreatedDateTime}, 'infinity'::timestamptz), ${batchOldestCreated})`,
      newestLastModifiedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestLastModifiedDateTime}, '-infinity'::timestamptz), ${batchNewestModified})`,
      oldestLastModifiedDateTime: sql`LEAST(COALESCE(${inboxConfiguration.oldestLastModifiedDateTime}, 'infinity'::timestamptz), ${batchOldestModified})`,
    });
  }

  private async updateInboxConfigByVersion(
    userProfileId: string,
    version: string,
    values: Partial<{ [key in keyof InboxConfiguration]: InboxConfiguration[key] | SQL<unknown> }>,
  ): Promise<boolean> {
    const result = await this.db
      .update(inboxConfiguration)
      .set(values)
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfileId),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .execute();

    return (result.rowCount ?? 0) > 0;
  }
}
