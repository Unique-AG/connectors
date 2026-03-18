import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { MessageEventDto } from './dtos/message-event.dto';
import { IngestFullSyncMessageCommand } from './ingest-full-sync-message.command';
import { IngestEmailLiveCatchupMessageCommand } from './ingest-live-catchup-message.command';
import { IngestionPriority } from './utils/ingestion-queue.utils';

@Injectable()
export class IngestionListener {
  private readonly logger = new Logger(IngestionListener.name);

  public constructor(
    private readonly ingestEmailLiveCatchupMessageCommand: IngestEmailLiveCatchupMessageCommand,
    private readonly ingestFullSyncMessageCommand: IngestFullSyncMessageCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.mail-events',
    routingKey: ['unique.outlook-semantic-mcp.mail-event.*'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
      maxPriority: IngestionPriority.High,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onIngestionRequested(@RabbitPayload() payload: unknown): Promise<void> {
    const event = MessageEventDto.parse(payload);
    this.logger.log({ msg: 'Email ingestion requested', type: event.type });

    switch (event.type) {
      case 'unique.outlook-semantic-mcp.mail-event.live-change-notification-received':
        return await this.ingestEmailLiveCatchupMessageCommand.run(event.payload);
      case 'unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled':
        return await this.ingestFullSyncMessageCommand.run(event.payload);
    }
  }
}
