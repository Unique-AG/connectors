import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { indexBy, isNonNullish } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopePathForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import {
  SubscriptionMailFilters,
  subscriptionMailFilters,
} from '../../db/schema/subscription/subscription-mail-filters.dto';
import { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { MessageEventDto } from '../mail-ingestion/dtos/message-event.dto';
import {
  FileDiffGraphMessage,
  FileDiffGraphMessageFields,
  fileDiffGraphMessageResponseSchema,
} from '../mail-ingestion/dtos/microsoft-graph.dtos';
import { getUniqueKeyForMessage } from '../mail-ingestion/utils/get-unique-key-for-message';
import { IngestionPriority } from '../mail-ingestion/utils/ingestion-queue.utils';
import { GetSubscriptionAndUserProfileQuery } from '../user-utils/get-subscription-and-user-profile.query';

export type FullSyncRunStatus = 'skipped' | 'success';

@Injectable()
export class FullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqp: AmqpConnection,
    private readonly getSubscriptionAndUserProfileQuery: GetSubscriptionAndUserProfileQuery,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(subscriptionId: string): Promise<{ status: FullSyncRunStatus }> {
    traceAttrs({ subscription_id: subscriptionId });
    this.logger.log({ subscriptionId, msg: `Starting full sync` });

    const { userProfile } =
      await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    traceAttrs({ user_profile_id: userProfile.id });
    const userEmail = createSmeared(userProfile.email);
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      userEmail,
      msg: `Resolved subscription and user profile`,
    });

    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfile.id));

    // Transactional concurrency guard: SELECT FOR UPDATE on inbox_configuration
    const guardResult = await this.db.transaction(async (tx) => {
      const result = await tx.execute<{
        sync_state: 'idle' | 'running' | 'failed';
        last_full_sync_run_at: string | null;
        filters: unknown;
      }>(
        sql`SELECT sync_state, last_full_sync_run_at, filters FROM inbox_configuration WHERE user_profile_id = ${userProfile.id} FOR UPDATE`,
      );
      const locked = result.rows[0];

      if (!locked) {
        return { kind: 'skipped', reason: 'missing' } as const;
      }

      if (locked.sync_state === 'running') {
        return { kind: 'skipped', reason: 'already running' } as const;
      }

      const twoDaysAgo = new Date();
      twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
      const lastFullSyncRunAt = locked.last_full_sync_run_at
        ? new Date(locked.last_full_sync_run_at)
        : null;
      if (isNonNullish(lastFullSyncRunAt) && lastFullSyncRunAt > twoDaysAgo) {
        return { kind: 'skipped', reason: 'ran recently', lastFullSyncRunAt } as const;
      }

      await tx
        .update(inboxConfiguration)
        .set({
          syncState: 'running',
          syncStartedAt: new Date(),
          messagesFromMicrosoft: 0,
          messagesQueuedForSync: 0,
          messagesProcessed: 0,
        })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();

      return { kind: 'proceed', filters: locked.filters } as const;
    });

    if (guardResult.kind === 'skipped') {
      if (guardResult.reason === 'ran recently') {
        traceEvent('full sync skipped', {
          reason: 'ran recently',
          last_full_sync_run_at: guardResult.lastFullSyncRunAt.toISOString(),
        });
        this.logger.log({
          subscriptionId,
          userProfileId: userProfile.id,
          userEmail,
          lastFullSyncRunAt: guardResult.lastFullSyncRunAt,
          msg: `Full sync skipped: ran recently`,
        });
      } else {
        traceEvent('full sync skipped', { reason: guardResult.reason });
        this.logger.log({
          subscriptionId,
          userProfileId: userProfile.id,
          userEmail,
          msg: `Full sync skipped: ${guardResult.reason}`,
        });
      }
      return { status: 'skipped' };
    }

    try {
      const filters = subscriptionMailFilters.parse(guardResult.filters);
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        dateFrom: filters.dateFrom,
        msg: `Fetching emails with filters`,
      });

      const allGraphEmails = await this.fetchAllEmails({
        userProfileId: userProfile.id,
        filters,
      });
      traceEvent('emails fetched', { count: allGraphEmails.length });
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        emailCount: allGraphEmails.length,
        msg: `Emails fetched`,
      });

      await this.db
        .update(inboxConfiguration)
        .set({ messagesFromMicrosoft: allGraphEmails.length })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();

      const filesList = allGraphEmails.map((item) => ({
        key: getUniqueKeyForMessage(userProfile.email, item),
        url: item.webLink,
        updatedAt: item.lastModifiedDateTime,
      }));

      const fileDiffResponse = await this.uniqueApi.ingestion.performFileDiff(
        filesList,
        getRootScopePathForUser(userProfile.email),
        INGESTION_SOURCE_KIND,
        INGESTION_SOURCE_NAME,
      );
      traceEvent('file diff completed', {
        new: fileDiffResponse.newFiles.length,
        updated: fileDiffResponse.updatedFiles.length,
        deleted: fileDiffResponse.deletedFiles.length,
        moved: fileDiffResponse.movedFiles.length,
      });
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        newFiles: fileDiffResponse.newFiles.length,
        updatedFiles: fileDiffResponse.updatedFiles.length,
        deletedFiles: fileDiffResponse.deletedFiles.length,
        movedFiles: fileDiffResponse.movedFiles.length,
        msg: `File diff completed`,
      });

      const filesRecord = indexBy(allGraphEmails, (item) =>
        getUniqueKeyForMessage(userProfile.email, item),
      );
      const toIngest = [...fileDiffResponse.updatedFiles, ...fileDiffResponse.newFiles];
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        count: toIngest.length,
        msg: `Publishing ingestion events`,
      });

      let messagesQueuedForSync = 0;
      for (const fileKey of toIngest) {
        const message = filesRecord[fileKey];
        assert.ok(message, `Missing message for file key: ${fileKey}`);
        const event = MessageEventDto.encode({
          type: 'unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled',
          payload: { messageId: message.id, userProfileId: userProfile.id },
        });
        await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
          priority: IngestionPriority.Low,
        });
        messagesQueuedForSync += 1;
      }

      await this.db
        .update(inboxConfiguration)
        .set({ messagesQueuedForSync })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();

      if (fileDiffResponse.movedFiles.length) {
        this.logger.error({
          msg: `We found moved files: ${fileDiffResponse.movedFiles.length}`,
          subscriptionId,
          userProfileId: userProfile.id,
          userEmail,
          keys: fileDiffResponse.movedFiles.join(', '),
        });
      }
      const filesToDelete = await this.uniqueApi.files.getByKeys(fileDiffResponse.deletedFiles);
      if (filesToDelete.length) {
        this.logger.log({
          subscriptionId,
          userProfileId: userProfile.id,
          userEmail,
          count: filesToDelete.length,
          msg: `Deleting files from unique`,
        });
        await this.uniqueApi.files.deleteByIds(filesToDelete.map((file) => file.id));
      }

      await this.db
        .update(inboxConfiguration)
        .set({ syncState: 'idle', lastFullSyncRunAt: new Date() })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();

      return { status: 'success' };
    } catch (error) {
      await this.db
        .update(inboxConfiguration)
        .set({ syncState: 'failed' })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();
      throw error;
    }
  }

  private async fetchAllEmails({
    filters,
    userProfileId,
  }: {
    filters: SubscriptionMailFilters;
    userProfileId: string;
  }): Promise<FileDiffGraphMessage[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let emailsRaw = await client
      .api(`me/messages`)
      .header('Prefer', 'IdType="ImmutableId"')
      .select(FileDiffGraphMessageFields)
      .filter(`createdDateTime gt ${filters.dateFrom.toISOString()}`)
      .orderby(`createdDateTime desc`)
      .top(200)
      .get();
    let emailResponse = fileDiffGraphMessageResponseSchema.parse(emailsRaw);
    const emails: FileDiffGraphMessage[] = emailResponse.value;

    while (emailResponse['@odata.nextLink']) {
      emailsRaw = await client
        .api(emailResponse['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      emailResponse = fileDiffGraphMessageResponseSchema.parse(emailsRaw);
      emails.push(...emailResponse.value);
    }
    return emails;
  }
}
