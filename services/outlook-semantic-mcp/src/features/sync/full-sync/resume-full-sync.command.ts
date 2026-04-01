import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';
import { FullSyncEventDto } from './full-sync-event.dto';

type ResumeResult =
  | { status: 'resumed' }
  | { status: 'not-found' }
  | { status: 'invalid-state'; currentState: string };

@Injectable()
export class ResumeFullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly amqp: AmqpConnection,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<ResumeResult> {
    const result = await this.db
      .update(inboxConfigurations)
      .set({ fullSyncState: 'waiting-for-ingestion' })
      .where(
        and(
          eq(inboxConfigurations.userProfileId, userProfileId),
          eq(inboxConfigurations.fullSyncState, 'paused'),
        ),
      )
      .execute();

    if ((result.rowCount ?? 0) > 0) {
      const event = FullSyncEventDto.parse({
        type: 'unique.outlook-semantic-mcp.full-sync.retrigger',
        payload: { userProfileId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);

      this.logger.log({ userProfileId, msg: 'Full sync resumed via retrigger event' });
      return { status: 'resumed' };
    }

    const config = await this.db.query.inboxConfigurations.findFirst({
      where: eq(inboxConfigurations.userProfileId, userProfileId),
    });

    if (!config) {
      return { status: 'not-found' };
    }

    return { status: 'invalid-state', currentState: config.fullSyncState };
  }
}
