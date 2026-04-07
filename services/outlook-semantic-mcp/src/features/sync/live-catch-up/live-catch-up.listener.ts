import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, inArray } from 'drizzle-orm';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import { greatestFrom } from '~/utils/greatest-from';
import { Nullish } from '~/utils/nullish';
import { LiveCatchUpCommand } from './live-catch-up.command';
import { LiveCatchUpEventDto } from './live-catch-up-event.dto';

@Injectable()
export class LiveCatchUpListener {
  private readonly logger = new Logger(LiveCatchUpListener.name);

  public constructor(
    private readonly liveCatchUpCommand: LiveCatchUpCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
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
    switch (event.type) {
      case 'unique.outlook-semantic-mcp.live-catch-up.execute': {
        await this.updateLastNotificationReceivedAt(
          event.payload.subscriptionId,
          event.payload.notificationReceivedAt,
        );
        return await this.liveCatchUpCommand.run({
          ...event.payload,
          liveCatchupOverlappingWindow: this.config.liveCatchupOverlappingWindowMinutes,
        });
      }
      case 'unique.outlook-semantic-mcp.live-catch-up.ready-recheck': {
        return await this.liveCatchUpCommand.run({
          ...event.payload,
          liveCatchupOverlappingWindow: this.config.liveCatchupRecheckOverlappingWindowMinutes,
        });
      }
      default: {
        this.logger.error({ msg: `Unsuported live catchup event type: ${JSON.stringify(event)}` });
      }
    }
  }

  private async updateLastNotificationReceivedAt(
    subscriptionId: string,
    notificationReceivedAt: Nullish<string>,
  ): Promise<void> {
    if (!notificationReceivedAt) {
      return;
    }
    const notificationTime = new Date(notificationReceivedAt);
    const isValidDate =
      notificationTime instanceof Date && !Number.isNaN(notificationTime.getTime());
    if (!isValidDate) {
      return;
    }
    await this.db
      .update(inboxConfigurations)
      .set({
        lastWebhookReceivedAt: greatestFrom(
          inboxConfigurations.lastWebhookReceivedAt,
          notificationTime,
        ),
      })
      .where(
        inArray(
          inboxConfigurations.userProfileId,
          this.db
            .select({ id: subscriptions.userProfileId })
            .from(subscriptions)
            .where(eq(subscriptions.subscriptionId, subscriptionId)),
        ),
      );
  }
}
