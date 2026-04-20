import { defaultNackErrorHandler, RabbitPayload, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { DeleteInboxDataEventDto } from './delete-inbox-data-event.dto';
import { ExecuteInboxDeletionCommand } from './execute-inbox-deletion.command';

@Injectable()
export class DeleteInboxDataListener {
  private readonly logger = new Logger(DeleteInboxDataListener.name);

  public constructor(private readonly executeInboxDeletion: ExecuteInboxDeletionCommand) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.delete-inbox-data',
    routingKey: ['unique.outlook-semantic-mcp.delete-inbox-data.execute'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onDeleteInboxData(@RabbitPayload() payload: unknown): Promise<void> {
    const event = DeleteInboxDataEventDto.parse(payload);
    const { userProfileId } = event.payload;

    this.logger.log({ userProfileId, msg: 'Delete inbox data event received, delegating to command' });

    await this.executeInboxDeletion.run(userProfileId);
  }
}
