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
    const { userProfile, subscription } =
      await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfile.id));
    const twoDaysAgo = new Date();
    twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
    if (
      isNonNullish(subscription.lastFullSyncRunAt) &&
      subscription.lastFullSyncRunAt > twoDaysAgo
    ) {
      return;
    }
    await this.db
      .update(subscriptions)
      .set({ lastFullSyncRunAt: new Date() })
      .where(eq(subscriptions.id, subscription.id))
      .execute();

    const filters = subscriptionMailFilters.parse(subscription.filters);

    const allGraphEmails = await this.fetchAllEmails({
      userProfileId: userProfile.id,
      filters,
    });
    traceEvent('emails fetched', { count: allGraphEmails.length });
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

    const filesRecord = indexBy(allGraphEmails, (item) =>
      getUniqueKeyForMessage(userProfile.email, item),
    );
    for (const fileKey of [...filleDiffResponse.updatedFiles, ...filleDiffResponse.newFiles]) {
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
