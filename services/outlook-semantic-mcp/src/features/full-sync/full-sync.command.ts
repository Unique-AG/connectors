import assert from 'node:assert';
import crypto from 'node:crypto';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
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
import { IngestionPriority } from '../mail-ingestion/utils/ingestion-queue.utils';
import { shouldSkipEmail } from '../mail-ingestion/utils/should-skip-email';
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
      return await this.runSync({
        subscriptionId,
        userProfile,
        userEmail,
        filters: guardResult.filters,
        version: guardResult.version,
      });
    } catch (error) {
      await this.db
        .update(inboxConfiguration)
        .set({ fullSyncState: 'failed' })
        .where(
          and(
            eq(inboxConfiguration.userProfileId, userProfile.id),
            eq(inboxConfiguration.fullSyncVersion, guardResult.version),
          ),
        )
        .execute();
      throw error;
    }
  }

  private async runSync({
    subscriptionId,
    userProfile,
    userEmail,
    filters: filtersRaw,
    version,
  }: {
    subscriptionId: string;
    userProfile: NonNullishProps<UserProfile, 'email'>;
    userEmail: Smeared;
    filters: Record<string, unknown> | null;
    version: string;
  }): Promise<{ status: FullSyncRunStatus }> {
    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfile.id));
    const filters = inboxConfigurationMailFilters.parse(filtersRaw);
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      userEmail,
      ignoredBefore: filters.ignoredBefore,
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
      .set({ fullSyncState: 'performing-file-diff' })
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfile.id),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .execute();

    const graphEmailsWithSkipResult = allGraphEmails.map((email) => ({
      email,
      skipCheckResult: shouldSkipEmail(email, filters, { userProfileId: userProfile.id }),
    }));

    const [filteredGraphEmails, skippedGraphEmails] = partition(
      graphEmailsWithSkipResult,
      (item) => !item.skipCheckResult.skip,
    );
    if (skippedGraphEmails.length > 0) {
      traceEvent('emails skipped by filter', {
        count: skippedGraphEmails.length,
        skippedGraphEmails: JSON.stringify(
          skippedGraphEmails.map((item) => ({
            id: item.email.id,
            internetMessageId: item.email.internetMessageId,
            skipCheckResult: item.skipCheckResult,
          })),
        ),
      });
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        skippedCount: skippedGraphEmails.length,
        msg: 'Emails skipped by filter',
      });
    }

    const filesList = filteredGraphEmails.map(({ email }) => ({
      key: getUniqueKeyForMessage(userProfile.email, email),
      url: email.webLink,
      updatedAt: email.lastModifiedDateTime,
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

    await this.db
      .update(inboxConfiguration)
      .set({ fullSyncState: 'processing-file-diff-changes', messagesFromMicrosoft: allGraphEmails.length })
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfile.id),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .execute();

    const filesRecord = indexBy(filteredGraphEmails, ({ email }) =>
      getUniqueKeyForMessage(userProfile.email, email),
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
      const message = filesRecord[fileKey]?.email;
      assert.ok(message, `Missing message for file key: ${fileKey}`);
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled',
        payload: { messageId: message.id, userProfileId: userProfile.id, fullSyncVersion: version },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.Low,
      });
      messagesQueuedForSync += 1;
    }

    await this.db
      .update(inboxConfiguration)
      .set({ messagesQueuedForSync })
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfile.id),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
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
      .set({ fullSyncState: 'full-sync-finished', lastFullSyncRunAt: new Date() })
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfile.id),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .execute();

    return { status: 'success' };
  }

  private async acquireSyncLock(userProfileId: string): Promise<AcquireLockResult> {
    return this.db.transaction(async (tx): Promise<AcquireLockResult> => {
      const inboxConfig = await tx
        .select({
          fullSyncState: inboxConfiguration.fullSyncState,
          lastFullSyncRunAt: inboxConfiguration.lastFullSyncRunAt,
          filters: inboxConfiguration.filters,
        })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!inboxConfig) {
        // We only reach this state unless somebody deleted the inbox connection in the meanwhile.
        return { kind: 'skipped', reason: 'missing' };
      }

      if (
        inboxConfig.fullSyncState !== 'full-sync-finished' &&
        inboxConfig.fullSyncState !== 'failed'
      ) {
        return {
          kind: 'skipped',
          reason: 'already running',
          filters: inboxConfig.filters,
          lastFullSyncRunAt: inboxConfig.lastFullSyncRunAt,
        };
      }

      // Before production release change to a reasonable number.
      const fiveMinutesAgo = new Date();
      fiveMinutesAgo.setMinutes(fiveMinutesAgo.getMinutes() - 5);
      if (
        isNonNullish(inboxConfig.lastFullSyncRunAt) &&
        inboxConfig.lastFullSyncRunAt > fiveMinutesAgo
      ) {
        return {
          kind: 'skipped',
          reason: 'ran recently',
          filters: inboxConfig.filters,
          lastFullSyncRunAt: inboxConfig.lastFullSyncRunAt,
        };
      }

      const version = crypto.randomUUID();

      await tx
        .update(inboxConfiguration)
        .set({
          fullSyncState: 'fetching-emails',
          fullSyncVersion: version,
          lastFullSyncStartedAt: new Date(),
          messagesFromMicrosoft: 0,
          messagesQueuedForSync: 0,
          messagesProcessed: 0,
        })
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      return {
        kind: 'proceed',
        version,
        filters: inboxConfig.filters,
        lastFullSyncRunAt: inboxConfig.lastFullSyncRunAt,
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
      .filter(`createdDateTime gt ${filters.ignoredBefore.toISOString()}`)
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
      version: string;
      filters: Record<string, unknown> | null;
      lastFullSyncRunAt: Date | null;
    };
