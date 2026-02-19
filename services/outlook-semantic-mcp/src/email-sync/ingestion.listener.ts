import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { MessageEventDto } from './mail-ingestion/dtos/messag-event.dto';
import { IngestEmailCommand } from './mail-ingestion/ingest-email.command';
import { IngestEmailViaSubscriptionCommand } from './mail-ingestion/ingest-email-via-subscription.command';
import { IngestionPriority } from './mail-ingestion/utils/ingestion-queue.utils';

@Injectable()
export class IngestionListener {
  private readonly logger = new Logger(IngestionListener.name);

  public constructor(
    private readonly ingestEmailViaSubscriptionCommand: IngestEmailViaSubscriptionCommand,
    private readonly ingestEmailCommand: IngestEmailCommand,
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
    this.logger.log(`Email ingestion requested: ${event.type}`);

    switch (event.type) {
      case 'unique.outlook-semantic-mcp.mail-event.live-change-notification-received':
        return await this.ingestEmailViaSubscriptionCommand.run(event.payload);
      case 'unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled':
        return await this.ingestEmailCommand.run(event.payload);
    }
  }
}
