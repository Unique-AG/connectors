import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { MessageEventDto } from './dtos/message-event.dto';
import { IngestEmailLiveCatchupMessageCommand } from './ingest-live-catchup-message.command';

@Injectable()
export class IngestionListener {
  private readonly logger = new Logger(IngestionListener.name);

  public constructor(
    private readonly ingestEmailLiveCatchupMessageCommand: IngestEmailLiveCatchupMessageCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.mail-events',
    routingKey: ['unique.outlook-semantic-mcp.mail-event.*'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
      channel: 'live-catchup-ingestion',
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onIngestionRequested(@RabbitPayload() payload: unknown): Promise<void> {
    const event = MessageEventDto.parse(payload);
    this.logger.log({ msg: 'Email ingestion requested', type: event.type });
    await this.ingestEmailLiveCatchupMessageCommand.run(event.payload);
  }
}
