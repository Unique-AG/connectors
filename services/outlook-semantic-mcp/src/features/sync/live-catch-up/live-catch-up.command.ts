import assert from 'node:assert';
import { UniqueApiClient, UniqueFile } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Attributes, Counter } from '@opentelemetry/api';
import { eq, sql } from 'drizzle-orm';
import { MetricService, Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions, userProfiles } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { SyncDirectoriesCommand } from '~/features/directories-sync/sync-directories.command';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { greatestFrom } from '~/utils/greatest-from';
import { isWithinCooldown } from '~/utils/is-within-cooldown';
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

@Injectable()
export class LiveCatchUpCommand {
  private readonly logger = new Logger(this.constructor.name);
  private readonly messagesProcessed: Counter<Attributes>;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly processEmailCommand: ProcessEmailCommand,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    metricService: MetricService,
  ) {
    this.messagesProcessed = metricService.getCounter('live_catchup_messagest_total', {
      description: 'Total messages processed during full sync',
    });
  }

  @Span()
  public async run(input: {
    liveCatchupOverlappingWindow: number;
    subscriptionId: string;
  }): Promise<void> {
    await withRetryAttempts({
      fn: () => this.runLiveCatchup(input),
      onError: rethrowRateLimitError,
      getResultFailure: () => 'failed',
    });
  }

  @Span()
  public async runLiveCatchup({
    subscriptionId,
    liveCatchupOverlappingWindow,
  }: {
    liveCatchupOverlappingWindow: number;
    subscriptionId: string;
  }): Promise<void> {
    traceAttrs({ subscriptionId });
    this.logger.log({
      subscriptionId,
      msg: 'Live catch-up triggered',
    });

    const userProfile = await this.db
      .select({
        userProfileId: userProfiles.id,
        userEmail: userProfiles.email,
        providerUserId: userProfiles.providerUserId,
      })
      .from(subscriptions)
      .innerJoin(userProfiles, eq(subscriptions.userProfileId, userProfiles.id))
      .where(eq(subscriptions.subscriptionId, subscriptionId))
      .then((rows) => rows[0]);
    if (!userProfile) {
      return;
    }

    assert.ok(userProfile.userEmail, `Missing email for: ${userProfile.userProfileId}`);

    const lockResult = await this.acquireLock(userProfile.userProfileId);
    if (lockResult.status === 'skip') {
      return;
    }

    // We run maximum 3 rounds to avoid an infinite loop here.
    for (let round = 0; round < 3; round++) {
      // If we got webhooks while we were running we will run once more but with a smaller overlapping window
      // because we have some fresh data which appeared while we were running.
      const overlappingWindowInMinutes = round > 0 ? 2 : liveCatchupOverlappingWindow;

      const runResult = await this.runLiveCatchupWithLock({
        watermark: lockResult.watermark,
        filters: lockResult.filters,
        user: {
          email: userProfile.userEmail,
          profileId: userProfile.userProfileId,
          providerId: userProfile.providerUserId,
        },
        subscriptionId,
        liveCatchupOverlappingWindow: overlappingWindowInMinutes,
      });

      if (runResult.status === 'failed') {
        return;
      }

      const inboxConfiguration = await this.db
        .select({ lastWebhookReceivedAt: inboxConfigurations.lastWebhookReceivedAt })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfile.userProfileId))
        .then((rows) => rows[0]);

      const shouldStopNextRound =
        !inboxConfiguration ||
        !inboxConfiguration.lastWebhookReceivedAt ||
        inboxConfiguration.lastWebhookReceivedAt < runResult.lastBatchQueriedAt;

      if (shouldStopNextRound) {
        return;
      }
      console.log(`___SECOND_ROUND_RUNNING`);
    }
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
        })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!inboxConfig) {
        this.logger.warn({ userProfileId, msg: 'No inbox configuration found, skipping' });
        return { status: 'skip' };
      }

      if (
        inboxConfig.liveCatchUpState === 'running' &&
        isWithinCooldown(inboxConfig.liveCatchUpHeartbeatAt, RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES)
      ) {
        this.logger.log({ userProfileId, msg: `Live catch-up already running. Skipping` });
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
  }): Promise<{ status: 'success'; lastBatchQueriedAt: Date } | { status: 'failed' }> {
    const logProps = Object.freeze({ userProfileId: user.profileId, subscriptionId });

    try {
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(user.profileId));

      const client = this.graphClientFactory.createClientForUser(user.profileId);

      const { lastBatchQueriedAt } = await this.processMessages({
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
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'ready', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, user.profileId))
        .execute();
      return { status: 'success', lastBatchQueriedAt };
    } catch (error) {
      this.logger.error({ ...logProps, err: error, msg: 'Failed to execute live catch-up' });
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'failed', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, user.profileId))
        .execute();
      return { status: 'failed' };
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
  }): Promise<{ lastBatchQueriedAt: Date }> {
    const processedIds = new Set<string>();
    let batchNumber = 0;
    const logContext = {
      userProfileId: user.profileId,
      providerUserId: user.providerId,
      userEmail: user.email.toString(),
    };

    watermark.setMinutes(watermark.getMinutes() - liveCatchupOverlappingWindow);

    let lastBatchQueriedAt = new Date();
    let emailsRaw = await client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(GraphMessageFields)
      // We cannot combine a createdDateTime filter with orderby on lastModifiedDateTime on the
      // Microsoft side (InefficientFilter). The ignoredBefore check is applied in-memory below.
      .filter(`lastModifiedDateTime ge ${watermark.toISOString()}`)
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

      this.logger.log({
        ...perOutcomeStats,
        userProfileId: user.profileId,
        batchNumber,
        batchSize: batch.length,
        msg: 'Batch processed',
      });

      if (!emailResponse['@odata.nextLink']) {
        break;
      }

      lastBatchQueriedAt = new Date();
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

    return { lastBatchQueriedAt };
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
