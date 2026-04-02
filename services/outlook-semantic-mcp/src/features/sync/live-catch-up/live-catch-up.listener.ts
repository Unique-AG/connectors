import {
  AmqpConnection,
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import { LiveCatchUpCommand } from './live-catch-up.command';
import { LiveCatchUpEventDto } from './live-catch-up-event.dto';

@Injectable()
export class LiveCatchUpListener {
  private readonly logger = new Logger(LiveCatchUpListener.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly amqpConnection: AmqpConnection,
    private readonly liveCatchUpCommand: LiveCatchUpCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.live-catch-up',
    routingKey: ['unique.outlook-semantic-mcp.live-catch-up.*'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onLiveCatchUpEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = LiveCatchUpEventDto.parse(payload);
    this.logger.log({ msg: 'Live catch-up event received', type: event.type });
    const result = await this.liveCatchUpCommand.run(event.payload);
    if (result === 'completed') {
      await this.republishIfThereArePendingMessages(event.payload.subscriptionId);
    }
  }

  private async republishIfThereArePendingMessages(subscriptionId: string): Promise<void> {
    // If the live catchup run succesfully - we check if we buffered any message ids meanwhile
    // if we buffered we will publish again for reprocessing.
    await this.db.transaction(async (tx) => {
      const subscription = await tx.query.subscriptions.findFirst({
        where: eq(subscriptions.subscriptionId, subscriptionId),
      });
      if (!subscription) {
        return;
      }
      // We lock the inbox configuration because we will republish the messages.
      const pendingLiveMessageIds = await tx
        .select({ pendingLiveMessageIds: inboxConfigurations.pendingLiveMessageIds })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, subscription.userProfileId))
        .for('update')
        .then((rows) => rows[0]?.pendingLiveMessageIds ?? []);

      if (!pendingLiveMessageIds.length) {
        return;
      }
      const payload = LiveCatchUpEventDto.parse({
        type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
        payload: { subscriptionId, messageIds: pendingLiveMessageIds },
      });
      // The event will try to lock the same row as above but we already hold the lock so it's safe to publish before update
      // because we publish the current array and we hold the lock -> after the publish we empty the array.
      await this.amqpConnection.publish(MAIN_EXCHANGE.name, payload.type, payload);
      await tx
        .update(inboxConfigurations)
        .set({ pendingLiveMessageIds: [] })
        .where(eq(inboxConfigurations.userProfileId, subscription.userProfileId));
    });
  }
}
