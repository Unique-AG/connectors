import assert from 'node:assert';
import crypto from 'node:crypto';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, isNull, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';
import { DeleteInboxDataEventDto } from './delete-inbox-data-event.dto';

export type DeleteInboxDataResult =
  | 'deletion-started'
  | 'deletion-already-in-progress'
  | 'inbox-already-deleted';

@Injectable()
export class DeleteInboxDataCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly amqp: AmqpConnection,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<DeleteInboxDataResult> {
    this.logger.log({ userProfileId, msg: 'Starting inbox deletion: removing Graph subscription' });

    const version = crypto.randomUUID();

    const updatedRows = await this.db
      .update(inboxConfigurations)
      .set({
        deletingInboxStartedAt: sql`NOW()`,
        deletingHeartbeatAt: null,
        fullSyncVersion: version,
        fullSyncState: 'ready',
        liveCatchUpState: 'ready',
        fullSyncNextLink: null,
        fullSyncBatchIndex: 0,
        fullSyncSkipped: 0,
        fullSyncScheduledForIngestion: 0,
        fullSyncFailedToUploadForIngestion: 0,
        fullSyncExpectedTotal: null,
        fullSyncLastRunAt: null,
      })
      .where(
        and(
          isNull(inboxConfigurations.deletingInboxStartedAt),
          eq(inboxConfigurations.userProfileId, userProfileId),
        ),
      )
      .returning();

    if (updatedRows.length > 0) {
      this.logger.log({
        userProfileId,
        version,
        msg: 'Deletion guard set, publishing delete-inbox-data.execute',
      });

      const event = DeleteInboxDataEventDto.parse({
        type: 'unique.outlook-semantic-mcp.delete-inbox-data.execute',
        payload: { userProfileId },
      });

      const published = await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
      assert.ok(published, `Cannot publish AMQP event "${event.type}"`);
      return 'deletion-started';
    }

    const inboxConfiguration = await this.db
      .select()
      .from(inboxConfigurations)
      .where(eq(inboxConfigurations.userProfileId, userProfileId))
      .then((rows) => rows[0]);

    if (!inboxConfiguration) {
      this.logger.log({
        userProfileId,
        version,
        msg: 'Inbox Configuration already deleted',
      });
      return 'inbox-already-deleted';
    }

    this.logger.log({
      userProfileId,
      version,
      msg: 'Inbox Configuration deletion in progress',
    });
    return 'deletion-already-in-progress';
  }
}
