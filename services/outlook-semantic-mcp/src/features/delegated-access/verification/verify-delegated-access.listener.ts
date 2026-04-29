import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { SyncDelegatedAccessEventDto } from './sync-delegated-access-event';
import { SyncDelegatedAccessForAllUsersCommand } from './sync-delegated-access-for-all-users.command';

@Injectable()
export class VerifyDelegatedAccessListener {
  private readonly logger = new Logger(VerifyDelegatedAccessListener.name);

  public constructor(
    private readonly syncDelegatedAccessForAllUsersCommand: SyncDelegatedAccessForAllUsersCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.delegated-access.verify',
    routingKey: ['unique.outlook-semantic-mcp.delegated-access.verify.*'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onVerifyDelegatedAccessEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = SyncDelegatedAccessEventDto.parse(payload);
    this.logger.log({ msg: 'Delegated access verification event received', type: event.type });
    await this.syncDelegatedAccessForAllUsersCommand.run();
  }
}
