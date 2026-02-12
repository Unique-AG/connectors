import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { isNonNullish, isNullish } from 'remeda';
import { z } from 'zod/v4';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, emailSyncStats, userProfiles } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MessageEventDto } from './dtos/message-events.dtos';
import {
  FileDiffGraphMessage,
  FileDiffGraphMessageFields,
  fileDiffGraphMessageResponseSchema,
} from './dtos/microsoft-graph.dtos';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';
import { IngestionPriority } from './utils/ingestion-queue.utils';

const syncFilters = z.object({
  createdAfter: z.date(),
});

type SyncFilters = z.infer<typeof syncFilters>;

@Injectable()
export class FullSyncCommand {
  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(userProfileId: string): Promise<void> {
    let emailSyncProgress = await this.db.query.emailSyncStats.findFirst({
      where: eq(emailSyncStats.userProfileId, userProfileId),
    });
    const twoDaysAgo = new Date();
    twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
    if (isNonNullish(emailSyncProgress) && emailSyncProgress.startedAt > twoDaysAgo) {
      return;
    }
    if (isNullish(emailSyncProgress)) {
      const result = await this.db
        .insert(emailSyncStats)
        .values({
          userProfileId,
          startedAt: new Date(),
        })
        .returning();
      emailSyncProgress = result[0];
    }
    assert.ok(emailSyncProgress, `Missing email sync progress`);
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `Missing User Profile: ${userProfile?.id}`);
    const userProfileEmail = userProfile.email;
    assert.ok(userProfileEmail, `Missing User Profile email: ${userProfile?.id}`);
    const filters = syncFilters.parse(emailSyncStats?.filters);

    const allGraphEmails = await this.fetchAllEmails({
      userProfileId,
      filters,
    });
    const filesList = allGraphEmails.map((item) => ({
      key: getUniqueKeyForMessage(userProfileEmail, item),
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
      acc[getUniqueKeyForMessage(userProfileEmail, item)] = item;
      return acc;
    }, {});
    for (const fileKey of [...filleDiffResponse.updatedFiles, ...filleDiffResponse.newFiles]) {
      const message = filesRecord[fileKey];
      assert.ok(message, `Missing message for file key: ${fileKey}`);
      const event = MessageEventDto.encode({
        type: 'unique.outlook-semantic-mcp.mail-notification.new-message',
        payload: { messageId: message.id, userProfileId },
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
        payload: { key: fileKey, messageId: message.id, userProfileId },
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
    filters: SyncFilters;
    userProfileId: string;
  }): Promise<FileDiffGraphMessage[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let emailsRaw = await client
      .api(`me/messages`)
      .header('Prefer', 'IdType="ImmutableId"')
      .select(FileDiffGraphMessageFields)
      .filter(`createdDateTime gt ${filters.createdAfter.toISOString()}`)
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
