import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { FullSyncCommand } from './full-sync.command';
import { FullSyncEventDto } from './full-sync-event.dto';

@Injectable()
export class FullSyncListener {
  private readonly logger = new Logger(FullSyncListener.name);

  public constructor(private readonly fullSyncCommand: FullSyncCommand) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.full-sync',
    routingKey: ['unique.outlook-semantic-mcp.full-sync.*'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onFullSyncEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = FullSyncEventDto.parse(payload);
    this.logger.log({ msg: 'Full sync event received', type: event.type });
    await this.fullSyncCommand.run(event.payload.userProfileId);
  }
}
