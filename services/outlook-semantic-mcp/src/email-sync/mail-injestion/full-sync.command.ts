import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GetSubscriptionAndUserProfileQuery } from '../subscription-utils/get-subscription-and-user-profile.query';
import { MessageEventDto } from './dtos/message-events.dtos';
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
  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqp: AmqpConnection,
    private readonly getSubscriptionAndUserProfileQuery: GetSubscriptionAndUserProfileQuery,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(subscriptionId: string): Promise<void> {
    const { userProfile, subscription } =
      await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
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
    const filesList = allGraphEmails.map((item) => ({
      key: getUniqueKeyForMessage(userProfile.email, item),
      url: item.webLink,
      updatedAt: item.lastModifiedDateTime,
    }));
    const _request = {
      partialKey: `TODO_DEFINE`,
      sourceKind: `TODO_DEFINE`,
      sourceName: `TODO_DEFINE`,
      filesList,
    };

    // TODO: File diff
    const filleDiffResponse: {
      newFiles: string[];
      updatedFiles: string[];
      movedFiles: string[];
      deletedFiles: string[];
    } = {
      newFiles: [],
      updatedFiles: [],
      movedFiles: [],
      deletedFiles: [],
    };

    const filesRecord = allGraphEmails.reduce<Record<string, FileDiffGraphMessage>>((acc, item) => {
      acc[getUniqueKeyForMessage(userProfile.email, item)] = item;
      return acc;
    }, {});
    for (const fileKey of [...filleDiffResponse.updatedFiles, ...filleDiffResponse.newFiles]) {
      const message = filesRecord[fileKey];
      assert.ok(message, `Missing message for file key: ${fileKey}`);
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-notification.new-message',
        payload: { messageId: message.id, userProfileId: userProfile.id },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.Low,
      });
    }

    for (const fileKey of filleDiffResponse.movedFiles) {
      const message = filesRecord[fileKey];
      assert.ok(message, `Missing message for file key: ${fileKey}`);
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-notification.message-metadata-changed',
        payload: {
          key: fileKey,
          messageId: message.id,
          userProfileId: userProfile.id,
        },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event, {
        priority: IngestionPriority.Low,
      });
    }
    for (const _fileKey of filleDiffResponse.deletedFiles) {
      // TODO: Delete
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
