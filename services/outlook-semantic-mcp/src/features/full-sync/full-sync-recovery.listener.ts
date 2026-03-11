import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { FullSyncRecoveryEventDto } from './dtos/full-sync-recovery-event.dto';
import { FullSyncCommand } from './full-sync.command';

@Injectable()
export class FullSyncRecoveryListener {
  private readonly logger = new Logger(FullSyncRecoveryListener.name);

  public constructor(
    private readonly fullSyncCommand: FullSyncCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.full-sync-recovery',
    routingKey: 'unique.outlook-semantic-mcp.full-sync.recovery-requested',
    createQueueIfNotExists: true,
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onRecoveryRequested(@RabbitPayload() payload: unknown): Promise<void> {
    const event = FullSyncRecoveryEventDto.parse(payload);
    const { userProfileId } = event.payload;

    this.logger.log({ msg: 'Full sync recovery requested', userProfileId });

    await this.db
      .update(inboxConfiguration)
      .set({ fullSyncState: 'full-sync-finished' })
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .execute();

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });

    if (!subscription) {
      this.logger.warn({
        msg: 'No subscription found for user profile during recovery, skipping full sync',
        userProfileId,
      });
      return;
    }

    this.logger.log({
      msg: 'Triggering full sync for recovered inbox',
      userProfileId,
      subscriptionId: subscription.subscriptionId,
    });

    await this.fullSyncCommand.run(subscription.subscriptionId);
  }
}
