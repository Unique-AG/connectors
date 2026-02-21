import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { indexBy, isNonNullish } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import { traceAttrs, traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopePath } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { GetSubscriptionAndUserProfileQuery } from '../user-utils/get-subscription-and-user-profile.query';
import { MessageEventDto } from './dtos/message-event.dto';
import {
  FileDiffGraphMessage,
  FileDiffGraphMessageFields,
  fileDiffGraphMessageResponseSchema,
} from './dtos/microsoft-graph.dtos';
import {
  SubscriptionMailFilters,
  subscriptionMailFilters,
} from './dtos/subscription-mail-filters.dto';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';
import { IngestionPriority } from './utils/ingestion-queue.utils';

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
  public async run(subscriptionId: string): Promise<void> {
    traceAttrs({ subscription_id: subscriptionId });
    this.logger.log({ subscriptionId, msg: `Starting full sync` });

    const { userProfile, subscription } =
      await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    traceAttrs({ user_profile_id: userProfile.id });
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      msg: `Resolved subscription and user profile`,
    });

    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfile.id));

    const twoDaysAgo = new Date();
    twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
    if (
      isNonNullish(subscription.lastFullSyncRunAt) &&
      subscription.lastFullSyncRunAt > twoDaysAgo
    ) {
      traceEvent('full sync skipped', {
        reason: 'ran recently',
        last_full_sync_run_at: subscription.lastFullSyncRunAt.toISOString(),
      });
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        lastFullSyncRunAt: subscription.lastFullSyncRunAt,
        msg: `Full sync skipped: ran recently`,
      });
      return;
    }
    await this.db
      .update(subscriptions)
      .set({ lastFullSyncRunAt: new Date() })
      .where(eq(subscriptions.id, subscription.id))
      .execute();

    const filters = subscriptionMailFilters.parse(subscription.filters);
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
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
      emailCount: allGraphEmails.length,
      msg: `Emails fetched`,
    });

    const filesList = allGraphEmails.map((item) => ({
      key: getUniqueKeyForMessage(userProfile.email, item),
      url: item.webLink,
      updatedAt: item.lastModifiedDateTime,
    }));

    const filleDiffResponse = await this.uniqueApi.ingestion.performFileDiff(
      filesList,
      getRootScopePath(userProfile.email),
      INGESTION_SOURCE_KIND,
      INGESTION_SOURCE_NAME,
    );
    traceEvent('file diff completed', {
      new: filleDiffResponse.newFiles.length,
      updated: filleDiffResponse.updatedFiles.length,
      deleted: filleDiffResponse.deletedFiles.length,
      moved: filleDiffResponse.movedFiles.length,
    });
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      newFiles: filleDiffResponse.newFiles.length,
      updatedFiles: filleDiffResponse.updatedFiles.length,
      deletedFiles: filleDiffResponse.deletedFiles.length,
      movedFiles: filleDiffResponse.movedFiles.length,
      msg: `File diff completed`,
    });

    const filesRecord = indexBy(allGraphEmails, (item) =>
      getUniqueKeyForMessage(userProfile.email, item),
    );
    const toIngest = [...filleDiffResponse.updatedFiles, ...filleDiffResponse.newFiles];
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      count: toIngest.length,
      msg: `Publishing ingestion events`,
    });
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
    }

    if (filleDiffResponse.movedFiles.length) {
      this.logger.error({
        msg: `We found moved files: ${filleDiffResponse.movedFiles.length}`,
        keys: filleDiffResponse.movedFiles.join(', '),
      });
    }
    const filesToDelete = await this.uniqueApi.files.getByKeys(filleDiffResponse.deletedFiles);
    if (filesToDelete.length) {
      this.logger.log({
        subscriptionId,
        userProfileId: userProfile.id,
        count: filesToDelete.length,
        msg: `Deleting files from unique`,
      });
      await this.uniqueApi.files.deleteByIds(filesToDelete.map((file) => file.id));
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
