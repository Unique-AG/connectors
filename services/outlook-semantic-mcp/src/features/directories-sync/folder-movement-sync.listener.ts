import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { FolderMovementSyncCommand } from './folder-movement-sync.command';
import { FolderMovementSyncEventDto } from './folder-movement-sync-event.dto';

@Injectable()
export class FolderMovementSyncListener {
  private readonly logger = new Logger(FolderMovementSyncListener.name);

  public constructor(private readonly folderMovementSyncCommand: FolderMovementSyncCommand) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.sync',
    routingKey: ['unique.outlook-semantic-mcp.sync.folder-movement'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onFolderMovementEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = FolderMovementSyncEventDto.parse(payload);
    this.logger.log({ msg: 'Folder movement sync event received', type: event.type });
    await this.folderMovementSyncCommand.run(event.payload.userProfileId);
  }
}
