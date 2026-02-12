import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { MessageEventDto } from './dtos/message-events.dtos';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestEmailViaSubscriptionCommand } from './ingest-email-via-subscription.command';
import { UpdateMetadataCommand } from './update-metadata.command';
import { IngestionPriority } from './utils/ingestion-queue.utils';

@Injectable()
export class IngestionListener {
  private readonly logger = new Logger(IngestionListener.name);

  public constructor(
    private readonly ingestEmailViaSubscriptionCommand: IngestEmailViaSubscriptionCommand,
    private readonly ingestEmailCommand: IngestEmailCommand,
    private readonly updateMetadataCommand: UpdateMetadataCommand,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.mail-notifications',
    routingKey: ['unique.outlook-semantic-mcp.mail-notification.*'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
      maxPriority: IngestionPriority.High,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onIngestionRequested(@RabbitPayload() payload: unknown): Promise<void> {
    const event = MessageEventDto.parse(payload);

    switch (event.type) {
      case 'unique.outlook-semantic-mcp.mail-notification.subscription-message-changed':
        return await this.ingestEmailViaSubscriptionCommand.run(event.payload);
      case 'unique.outlook-semantic-mcp.mail-notification.new-message':
        return await this.ingestEmailCommand.run(event.payload);
      case 'unique.outlook-semantic-mcp.mail-notification.message-metadata-changed':
        return await this.updateMetadataCommand.run(event.payload);
    }
  }
}
