import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { indexBy, isNonNullish, partition } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, UserProfile } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopePathForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '../../db/schema/inbox/inbox-configuration-mail-filters.dto';
import { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { MessageEventDto } from '../mail-ingestion/dtos/message-event.dto';
import {
  FileDiffGraphMessage,
  FileDiffGraphMessageFields,
  fileDiffGraphMessageResponseSchema,
} from '../mail-ingestion/dtos/microsoft-graph.dtos';
import { getUniqueKeyForMessage } from '../mail-ingestion/utils/get-unique-key-for-message';
import { shouldSkipEmail } from '../mail-ingestion/utils/should-skip-email';
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
    traceAttrs({ subscriptionId: subscriptionId });
    this.logger.log({ subscriptionId, msg: `Starting full sync` });

    const { userProfile } = await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    const userEmail = createSmeared(userProfile.email);
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      userEmail,
      msg: `Resolved subscription and user profile`,
    });

    const guardResult = await this.acquireSyncLock(userProfile.id);
    if (guardResult.kind === 'skipped') {
      const attributes = {
        reason: guardResult.reason,
        lastFullSyncRunAt:
          guardResult.reason !== 'missing' ? guardResult.lastFullSyncRunAt?.toISOString() : `null`,
      };
      traceEvent('full sync skipped', attributes);
      this.logger.log({
        ...attributes,
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        msg: `Full sync skipped: ${guardResult.reason}`,
      });
      return { status: 'skipped' };
    }

    try {
      return this.runSync({ subscriptionId, userProfile, userEmail, filters: guardResult.filters });
    } catch (error) {
      await this.db
        .update(inboxConfiguration)
        .set({ syncState: 'failed' })
        .where(eq(inboxConfiguration.userProfileId, userProfile.id))
        .execute();
      throw error;
    }
  }

  private async runSync({
    subscriptionId,
    userProfile,
    userEmail,
    filters: filtersRaw,
  }: {
    subscriptionId: string;
    userProfile: NonNullishProps<UserProfile, 'email'>;
    userEmail: Smeared;
    filters: Record<string, unknown> | null;
  }): Promise<{ status: FullSyncRunStatus }> {
    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfile.id));
    const filters = inboxConfigurationMailFilters.parse(filtersRaw);
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

    const [filteredGraphEmails, skippedGraphEmails] = partition(
      allGraphEmails,
      (item) => !shouldSkipEmail(item, filters, { userProfileId: userProfile.id }).skip,
    );
    if (skippedGraphEmails.length > 0) {
      traceEvent('emails skipped by filter', { count: skippedGraphEmails.length });
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        skippedCount: skippedGraphEmails.length,
        msg: 'Emails skipped by filter',
      });
    }

    const filesList = filteredGraphEmails.map((item) => ({
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

    const filesRecord = indexBy(filteredGraphEmails, (item) =>
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
  }

  private async acquireSyncLock(userProfileId: string): Promise<AcquireLockResult> {
    return this.db.transaction(async (tx): Promise<AcquireLockResult> => {
      const locked = await tx
        .select({
          syncState: inboxConfiguration.syncState,
          lastFullSyncRunAt: inboxConfiguration.lastFullSyncRunAt,
          filters: inboxConfiguration.filters,
        })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!locked) {
        return { kind: 'skipped', reason: 'missing' };
      }

      if (locked.syncState === 'running') {
        return {
          kind: 'skipped',
          reason: 'already running',
          filters: locked.filters,
          lastFullSyncRunAt: locked.lastFullSyncRunAt,
        };
      }

      const twoDaysAgo = new Date();
      twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
      if (isNonNullish(locked.lastFullSyncRunAt) && locked.lastFullSyncRunAt > twoDaysAgo) {
        return {
          kind: 'skipped',
          reason: 'ran recently',
          filters: locked.filters,
          lastFullSyncRunAt: locked.lastFullSyncRunAt,
        };
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
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      return {
        kind: 'proceed',
        filters: locked.filters,
        lastFullSyncRunAt: locked.lastFullSyncRunAt,
      };
    });
  }

  private async fetchAllEmails({
    filters,
    userProfileId,
  }: {
    filters: InboxConfigurationMailFilters;
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

type AcquireLockResult =
  | { kind: 'skipped'; reason: 'missing' }
  | {
      kind: 'skipped';
      reason: 'already running' | 'ran recently';
      filters: Record<string, unknown> | null;
      lastFullSyncRunAt: Date | null;
    }
  | {
      kind: 'proceed';
      filters: Record<string, unknown> | null;
      lastFullSyncRunAt: Date | null;
    };
