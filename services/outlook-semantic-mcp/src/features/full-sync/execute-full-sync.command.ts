import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, SQL, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
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

export const START_DELTA_LINK = `SYNC_STARTED:__EMPTY_DELTA__`;

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
        fullSyncNextLink: inboxConfiguration.fullSyncNextLink,
      })
      .from(inboxConfiguration)
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .then((rows) => rows[0]);

    if (!inboxConfig) {
      this.logger.warn({ userProfileId, version, msg: 'No inbox configuration found, discarding' });
      return;
    }

    const { fullSyncNextLink, fullSyncVersion, fullSyncState } = inboxConfig;
    if (!fullSyncNextLink) {
      this.logger.warn({
        userProfileId,
        version,
        msg: 'Delta link is null cannot resume this full sync',
      });
      return;
    }

    if (fullSyncVersion !== version || fullSyncState !== 'fetching-emails') {
      this.logger.log({
        userProfileId,
        version,
        currentVersion: fullSyncVersion,
        currentState: fullSyncState,
        msg: 'Stale execute event, discarding',
      });
      return;
    }

    const filters = inboxConfigurationMailFilters.parse(inboxConfig.filters);

    try {
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfileId));

      this.logger.log({
        userProfileId,
        version,
        ignoredBefore: filters.ignoredBefore,
        msg: 'Fetching emails in batches',
      });

      await this.fetchAndScheduleBatches({
        userProfileId,
        filters,
        version,
        initialDeltaLink: fullSyncNextLink,
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
    initialDeltaLink,
  }: {
    userProfileId: string;
    filters: InboxConfigurationMailFilters;
    version: string;
    initialDeltaLink: string;
  }): Promise<void> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    let totalScheduled = 0;
    let batchNumber = 0;

    const fetchBatch = async (nextLink: string): Promise<unknown> => {
      const conditions = [`createdDateTime gt ${filters.ignoredBefore.toISOString()}`];

      if (nextLink !== START_DELTA_LINK) {
        try {
          return await client.api(nextLink).header('Prefer', 'IdType="ImmutableId"').get();
        } catch (error) {
          const isExpiredNextLink = error instanceof GraphError && error.statusCode === 410;
          if (!isExpiredNextLink) {
            throw error;
          }

          // Read fresh from DB so the cutoff reflects watermarks written by batches already
          // processed in this run, not the snapshot captured before the sync started.
          const oldestCreatedDateTime = await this.db
            .select({ oldestCreatedDateTime: inboxConfiguration.oldestCreatedDateTime })
            .from(inboxConfiguration)
            .where(
              and(
                eq(inboxConfiguration.userProfileId, userProfileId),
                eq(inboxConfiguration.fullSyncVersion, version),
              ),
            )
            .then((rows) => rows[0]?.oldestCreatedDateTime ?? new Date());

          conditions.push(`createdDateTime lte ${oldestCreatedDateTime.toISOString()}`);
        }
      }
      return await client
        .api(`me/messages`)
        .header('Prefer', 'IdType="ImmutableId"')
        .select(FullSyncGraphMessageFields)
        .filter(conditions.join(' and '))
        .orderby(`createdDateTime desc`)
        .top(200)
        .get();
    };

    let nextLink: string | null = initialDeltaLink;

    while (nextLink) {
      const emailsRaw = await fetchBatch(nextLink);
      const emailResponse = fullSyncGraphMessageResponseSchema.parse(emailsRaw);
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

      nextLink = emailResponse['@odata.nextLink'] ?? null;
      await this.updateInboxConfigByVersion(userProfileId, version, {
        fullSyncNextLink: nextLink,
      });
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
