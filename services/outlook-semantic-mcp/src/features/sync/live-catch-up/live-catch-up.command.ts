import { UniqueApiClient, UniqueFile } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { assert } from 'vitest';
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
import {
  GraphMessage,
  GraphMessageFields,
  graphMessagesResponseSchema,
} from '../../process-email/dtos/microsoft-graph.dtos';
import { ProcessEmailCommand } from '../../process-email/process-email.command';

export const RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES = 20;
export const FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES = 5;
export const READY_LIVE_CATCHUP_THRESHOLD_MINUTES = 60 * 4;

@Injectable()
export class LiveCatchUpCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly processEmailCommand: ProcessEmailCommand,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run({
    subscriptionId,
    liveCatchupOverlappingWindow,
  }: {
    liveCatchupOverlappingWindow: number;
    subscriptionId: string;
  }): Promise<'skipped' | 'completed' | 'failed'> {
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
      .then((rows) => rows[0]);
    if (!userProfile) {
      return 'skipped';
    }

    assert.ok(userProfile.userEmail, `Missing email for: ${userProfile.userProfileId}`);

    const lockResult = await this.acquireLock(userProfile.userProfileId);
    if (lockResult.status === 'skip') {
      return 'skipped';
    }

    const { watermark, filters } = lockResult;

    try {
      await this.syncDirectoriesCommand.run(
        convertUserProfileIdToTypeId(userProfile.userProfileId),
      );

      const client = this.graphClientFactory.createClientForUser(userProfile.userProfileId);

      await this.processMessages({
        user: {
          email: createSmeared(userProfile.userEmail),
          profileId: userProfile.userProfileId,
          providerId: userProfile.providerUserId,
        },
        liveCatchupOverlappingWindow,
        client,
        watermark,
        filters,
      });

      this.logger.log({
        userProfileId: userProfile.userProfileId,
        subscriptionId,
        msg: 'Live catch-up completed',
      });
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'ready', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, userProfile.userProfileId))
        .execute();
      return 'completed';
    } catch (error) {
      this.logger.error({
        err: error,
        msg: 'Failed to execute live catch-up',
        userProfileId: userProfile.userProfileId,
        subscriptionId,
      });
      await this.db
        .update(inboxConfigurations)
        .set({ liveCatchUpState: 'failed', liveCatchUpHeartbeatAt: sql`NOW()` })
        .where(eq(inboxConfigurations.userProfileId, userProfile.userProfileId))
        .execute();
      return 'failed';
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
  }): Promise<Set<string>> {
    const processedIds = new Set<string>();
    let batchNumber = 0;

    watermark.setMinutes(watermark.getMinutes() - liveCatchupOverlappingWindow);

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

        if (result === 'failed') {
          this.logger.warn({
            userProfileId: user.profileId,
            messageId: graphMessage.id,
            msg: 'Email ingestion failed, continuing',
          });
        }

        await this.updateWatermarks({ email: graphMessage, userProfileId: user.profileId });
        processedIds.add(graphMessage.id);
      }

      this.logger.log({
        userProfileId: user.profileId,
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
      emailResponse = graphMessagesResponseSchema.parse(emailsRaw);
    }

    traceEvent('live catch-up batches completed', {
      processedCount: processedIds.size,
      batchCount: batchNumber,
    });

    return processedIds;
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
