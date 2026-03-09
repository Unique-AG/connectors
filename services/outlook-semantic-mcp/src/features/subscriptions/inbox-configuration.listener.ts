import assert from 'node:assert';
import { defaultNackErrorHandler, RabbitPayload, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { appConfig, type AppConfig } from '~/config';
import { DRIZZLE, type DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { FullSyncCommand } from '../full-sync/full-sync.command';
import { SubscriptionCreatedEventDto } from './subscription.dtos';

@Injectable()
export class InboxConfigurationListener {
  private readonly logger = new Logger(InboxConfigurationListener.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    private readonly fullSyncCommand: FullSyncCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.mail.inbox-configuration',
    routingKey: ['unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-created'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onSubscriptionCreated(@RabbitPayload() payload: unknown): Promise<void> {
    const event = SubscriptionCreatedEventDto.parse(payload);
    this.logger.log({ subscriptionId: event.subscriptionId, msg: 'Subscription created event received' });

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.subscriptionId, event.subscriptionId),
    });
    assert.ok(subscription, `Subscription missing for: ${event.subscriptionId}`);

    await this.db
      .insert(inboxConfiguration)
      .values({
        userProfileId: subscription.userProfileId,
        filters: this.config.defaultMailFilters,
      })
      .onConflictDoNothing();

    this.logger.log({
      subscriptionId: event.subscriptionId,
      userProfileId: subscription.userProfileId,
      msg: 'Inbox configuration upserted',
    });

    await this.fullSyncCommand.run(event.subscriptionId);
  }
}
