import assert from 'node:assert';
import { UniqueApiClient, UniqueFile } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Attributes, Counter, Histogram } from '@opentelemetry/api';
import { eq, sql } from 'drizzle-orm';
import { MetricService, Span } from 'nestjs-otel';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions, userProfiles } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { IsInboxDeletingQuery } from '~/features/delete-inbox/is-inbox-deleting.query';
import { SyncDirectoriesCommand } from '~/features/directories-sync/sync-directories.command';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { NewTrace, traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { greatestFrom } from '~/utils/greatest-from';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { isWithinCooldown } from '~/utils/is-within-cooldown';
import { recordInHistogram } from '~/utils/record-in-histogram';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';
import {
  GraphMessage,
  GraphMessageFields,
  graphMessagesResponseSchema,
} from '../../process-email/dtos/microsoft-graph.dtos';
import { ProcessEmailCommand } from '../../process-email/process-email.command';

export const RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES = 20;
export const FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES = 5;
export const READY_LIVE_CATCHUP_THRESHOLD_MINUTES = 30;

type LiveCatchupResult = { status: 'completed' | 'skipped' } | { status: 'failed'; err: unknown };

@Injectable()
export class LiveCatchUpCommand {
  private readonly logger = new Logger(this.constructor.name);
  private readonly messagesProcessed: Counter<Attributes>;
  private readonly liveCatchupRunDuration: Histogram;
  private readonly liveCatchupRoundDuration: Histogram;
  private readonly directorySyncDuration: Histogram;
  private readonly batchSyncDuration: Histogram;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly processEmailCommand: ProcessEmailCommand,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    private readonly isInboxDeletingQuery: IsInboxDeletingQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    metricService: MetricService,
  ) {
    this.messagesProcessed = metricService.getCounter('osm_live_catchup_messages_total', {
      description: 'Total messages processed during live catch-up',
    });
    this.liveCatchupRunDuration = metricService.getHistogram(
      'osm_live_catchup_run_duration_seconds',
      {
        description: 'Wall-clock duration of a total live catch-up run() call',
      },
    );
    this.liveCatchupRoundDuration = metricService.getHistogram(
      'osm_live_catchup_round_duration_seconds',
      {
        description: 'Wall-clock duration of a live catch-up runLiveCatchup() call',
      },
    );
    this.directorySyncDuration = metricService.getHistogram(
      'osm_live_catchup_directory_sync_duration_seconds',
      {
        description: 'Duration of directory sync during live catch-up',
      },
    );
    this.batchSyncDuration = metricService.getHistogram('osm_live_catchup_batch_duration_seconds', {
      description: 'Duration of a single batch processing step during live catch-up',
    });
  }

  @NewTrace('live-catchup')
  public async run(input: {
    liveCatchupOverlappingWindow: number;
    subscriptionId: string;
  }): Promise<LiveCatchupResult> {
    traceAttrs({ subscriptionId: input.subscriptionId });
    return recordInHistogram({
      histogram: this.liveCatchupRunDuration,
      successAtrributes: (result) => ({
        status: result.status,
        errorType:
          result.status === 'failed'
            ? isRateLimitError(result.err)
              ? 'throttling'
              : 'other'
            : undefined,
      }),
      errorAttributtes: (error) => ({
        status: 'failed',
        errorType: isRateLimitError(error) ? 'throttling' : 'other',
      }),
      fn: () =>
        withRetryAttempts<LiveCatchupResult>({
          fn: () => this.runLiveCatchup(input),
          onError: rethrowRateLimitError,
          getResultFailure: (err) => ({ status: 'failed', err }),
        }),
    });
  }

  @Span()
  public async runLiveCatchup({
    subscriptionId,
    liveCatchupOverlappingWindow,
  }: {
    liveCatchupOverlappingWindow: number;
    subscriptionId: string;
  }): Promise<LiveCatchupResult> {
    traceAttrs({ subscriptionId });
    this.logger.debug({
      subscriptionId,
      msg: 'Live catch-up triggered',
    });
    if (this.config.mcpBackend === 'MicrosoftGraph') {
      return { status: 'skipped' };
    }

    const userProfileRow = await this.db
      .select({
        userProfileId: userProfiles.id,
        userEmail: userProfiles.email,
        providerUserId: userProfiles.providerUserId,
      })
      .from(subscriptions)
      .innerJoin(userProfiles, eq(subscriptions.userProfileId, userProfiles.id))
      .where(eq(subscriptions.subscriptionId, subscriptionId))
      .then((rows) => rows[0]);
    if (!userProfileRow) {
      return { status: 'skipped' };
    }
    if (await this.isInboxDeletingQuery.run(userProfileRow.userProfileId)) {
      return { status: 'skipped' };
    }

    const userProfileEmail = userProfileRow.userEmail;
    assert.ok(userProfileEmail, `Missing email for: ${userProfileRow.userProfileId}`);
    const userProfile = { ...userProfileRow, userEmail: userProfileEmail };

    const lockResult = await this.acquireLock(userProfile.userProfileId);
    if (lockResult.status === 'skip') {
      return { status: 'skipped' };
    }

    let finalStatus: 'ready' | 'failed' = 'ready';
    let finalOutput: LiveCatchupResult = { status: 'skipped' };

    try {
      // We run maximum 3 rounds to avoid an infinite loop here.
      for (let round = 0; round < 3; round++) {
        finalStatus = 'ready';
        // If we got webhooks while we were running we will run once more but with a smaller overlapping window
        // because we have some fresh data which appeared while we were running.
        const overlappingWindowInMinutes = round > 0 ? 2 : liveCatchupOverlappingWindow;

        const runResult = await recordInHistogram({
          histogram: this.liveCatchupRoundDuration,
          attributes: { roundNumber: round },
          successAtrributes: (result) => ({
            status: result.status,
            errorType:
              result.status === 'failed'
                ? isRateLimitError(result.err)
                  ? 'throttling'
                  : 'other'
                : undefined,
          }),
          errorAttributtes: (error) => ({
            status: 'failed',
            errorType: isRateLimitError(error) ? 'throttling' : 'other',
          }),
          fn: () =>
            this.runLiveCatchupWithLock({
              watermark: lockResult.watermark,
              filters: lockResult.filters,
              user: {
                email: userProfile.userEmail,
                profileId: userProfile.userProfileId,
                providerId: userProfile.providerUserId,
              },
              subscriptionId,
              liveCatchupOverlappingWindow: overlappingWindowInMinutes,
            }),
        });

        if (runResult.status === 'failed') {
          if (isRateLimitError(runResult.err)) {
            // We rethrow rate limit errors
            throw runResult.err;
          }
          finalOutput = { status: 'failed', err: runResult.err };
          finalStatus = 'failed';
          break;
        }

        finalOutput = { status: 'completed' };
        const inboxConfiguration = await this.db
          .select({
            lastWebhookReceivedAt: inboxConfigurations.lastWebhookReceivedAt,
            deletingInboxStartedAt: inboxConfigurations.deletingInboxStartedAt,
          })
          .from(inboxConfigurations)
          .where(eq(inboxConfigurations.userProfileId, userProfile.userProfileId))
          .then((rows) => rows[0]);

        if (inboxConfiguration?.deletingInboxStartedAt) {
          break;
        }

        if (
          !inboxConfiguration?.lastWebhookReceivedAt ||
          inboxConfiguration.lastWebhookReceivedAt < runResult.batchProcessingStartedAt
        ) {
          break;
        }
      }
    } finally {
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: finalStatus, liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, userProfile.userProfileId))
        .execute();
    }

    return finalOutput;
  }

  private async acquireLock(
    userProfileId: string,
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
          deletingInboxStartedAt: inboxConfigurations.deletingInboxStartedAt,
        })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!inboxConfig) {
        this.logger.warn({ userProfileId, msg: 'No inbox configuration found, skipping' });
        return { status: 'skip' };
      }

      if (inboxConfig.deletingInboxStartedAt !== null) {
        this.logger.debug({
          userProfileId,
          msg: 'Inbox deletion in progress, skipping live catch-up',
        });
        return { status: 'skip' };
      }

      if (
        inboxConfig.liveCatchUpState === 'running' &&
        isWithinCooldown(inboxConfig.liveCatchUpHeartbeatAt, RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES)
      ) {
        this.logger.debug({ userProfileId, msg: `Live catch-up already running. Skipping` });
        return { status: 'skip' };
      }

      await tx
        .update(inboxConfigurations)
        .set({
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

  private async runLiveCatchupWithLock({
    watermark,
    user,
    subscriptionId,
    filters,
    liveCatchupOverlappingWindow,
  }: {
    watermark: Date;
    filters: InboxConfigurationMailFilters;
    user: { profileId: string; providerId: string; email: string };
    subscriptionId: string;
    liveCatchupOverlappingWindow: number;
  }): Promise<
    { status: 'success'; batchProcessingStartedAt: Date } | { status: 'failed'; err: unknown }
  > {
    const logProps = Object.freeze({ userProfileId: user.profileId, subscriptionId });

    try {
      await recordInHistogram({
        histogram: this.directorySyncDuration,
        attributes: {},
        fn: () => this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(user.profileId)),
      });

      const client = this.graphClientFactory.createClientForUser(user.profileId);

      const { batchProcessingStartedAt } = await this.processMessages({
        user: {
          email: createSmeared(user.email),
          profileId: user.profileId,
          providerId: user.providerId,
        },
        liveCatchupOverlappingWindow,
        client,
        watermark,
        filters,
      });

      this.logger.log({ ...logProps, msg: 'Live catch-up completed' });
      return { status: 'success', batchProcessingStartedAt };
    } catch (error) {
      this.logger.error({ ...logProps, err: error, msg: 'Failed to execute live catch-up' });
      return { status: 'failed', err: error };
    }
  }

  private async processMessages({
    user,
    client,
    watermark,
    filters,
    liveCatchupOverlappingWindow,
  }: {
    user: {
      email: Smeared;
      profileId: string;
      providerId: string;
    };
    liveCatchupOverlappingWindow: number;
    client: Client;
    watermark: Date;
    filters: InboxConfigurationMailFilters;
  }): Promise<{ batchProcessingStartedAt: Date }> {
    const processedIds = new Set<string>();
    let batchNumber = 0;
    const logContext = {
      userProfileId: user.profileId,
      providerUserId: user.providerId,
      userEmail: user.email.toString(),
    };
    // We clone it because we modify it.
    const lastModifiedDateTime = new Date(watermark);
    lastModifiedDateTime.setMinutes(
      lastModifiedDateTime.getMinutes() - liveCatchupOverlappingWindow,
    );

    const batchProcessingStartedAt = new Date();
    let emailsRaw = await client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(GraphMessageFields)
      // We cannot combine a receivedDateTime filter with orderby on lastModifiedDateTime on the
      // Microsoft side (InefficientFilter). The retentionWindowInDays check is applied by processEmailCommand
      .filter(`lastModifiedDateTime ge ${lastModifiedDateTime.toISOString()}`)
      .orderby('lastModifiedDateTime asc')
      .top(200)
      .get();
    let emailResponse = graphMessagesResponseSchema.parse(emailsRaw);

    while (true) {
      batchNumber++;
      const batch = emailResponse.value;

      if (batch.length === 0) {
        break;
      }

      const batchStart = Date.now();
      const fileKeys = batch.map((item) =>
        getUniqueKeyForMessage({ userEmail: user.email.value, messageId: item.id }),
      );
      const uniqueFiles = await this.uniqueApi.files.getByKeys(fileKeys);
      const uniqueFilesHashMap = uniqueFiles.reduce<Record<string, UniqueFile>>((acc, file) => {
        acc[file.key] = file;
        return acc;
      }, {});
      const perOutcomeStats: Record<string, number> = {};

      this.logger.debug({
        ...logContext,
        msg: `Processing batch`,
        batchSize: batch.length,
        numberOfFilesFoundInUnique: uniqueFiles.length,
      });

      for (const graphMessage of batch) {
        const fileKey = getUniqueKeyForMessage({
          userEmail: user.email.value,
          messageId: graphMessage.id,
        });
        const result = await this.processEmailCommand.run({
          user,
          client,
          file: uniqueFilesHashMap[fileKey] ?? null,
          fileKey,
          filters,
          graphMessage,
        });
        const key = `totalMessages_${result}`;
        perOutcomeStats[key] = (perOutcomeStats[key] ?? 0) + 1;
        this.messagesProcessed.add(1, { outcome: result });
        await this.updateWatermarks({ email: graphMessage, userProfileId: user.profileId });
        processedIds.add(graphMessage.id);
      }

      this.logger.debug({
        ...perOutcomeStats,
        userProfileId: user.profileId,
        batchNumber,
        batchSize: batch.length,
        msg: 'Batch processed',
      });
      this.batchSyncDuration.record((Date.now() - batchStart) / 1000);

      if (!emailResponse['@odata.nextLink']) {
        break;
      }

      emailsRaw = await client
        .api(emailResponse['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      emailResponse = graphMessagesResponseSchema.parse(emailsRaw);
    }

    traceEvent('live catch-up batches completed', {
      processedCount: processedIds.size,
      batchCount: batchNumber,
    });

    return { batchProcessingStartedAt };
  }

  private async updateWatermarks({
    email,
    userProfileId,
  }: {
    email: GraphMessage;
    userProfileId: string;
  }): Promise<void> {
    const receivedDateTime = new Date(email.receivedDateTime);
    const lastModifiedDateTime = new Date(email.lastModifiedDateTime);

    await this.db
      .update(inboxConfigurations)
      .set({
        newestReceivedEmailDateTime: greatestFrom(
          inboxConfigurations.newestReceivedEmailDateTime,
          receivedDateTime,
        ),
        newestLastModifiedDateTime: greatestFrom(
          inboxConfigurations.newestLastModifiedDateTime,
          lastModifiedDateTime,
        ),
        liveCatchUpHeartbeatAt: sql`NOW()`,
      })
      .where(eq(inboxConfigurations.userProfileId, userProfileId))
      .execute();
  }
}
