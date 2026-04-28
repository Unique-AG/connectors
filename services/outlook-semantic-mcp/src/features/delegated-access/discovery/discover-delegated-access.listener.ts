import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { DiscoverDelegatedAccessCommand } from './discover-delegated-access.command';
import { DiscoverDelegatedAccessEventDto } from './discover-delegated-access-event.dto';

@Injectable()
export class DiscoverDelegatedAccessListener {
  private readonly logger = new Logger(DiscoverDelegatedAccessListener.name);

  public constructor(
    private readonly discoverDelegatedAccessCommand: DiscoverDelegatedAccessCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.delegated-access.discover',
    routingKey: ['unique.outlook-semantic-mcp.delegated-access.discover.*'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onDiscoverDelegatedAccessEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = DiscoverDelegatedAccessEventDto.parse(payload);
    this.logger.log({ msg: 'Delegated access discovery event received', type: event.type });
    await this.discoverDelegatedAccessCommand.run({
      delegateUserId: event.payload.delegateUserId,
    });
  }
}
