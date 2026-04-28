import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { VerifyDelegatedAccessCommand } from './verify-delegated-access.command';
import { VerifyDelegatedAccessEventDto } from './verify-delegated-access-event.dto';

@Injectable()
export class VerifyDelegatedAccessListener {
  private readonly logger = new Logger(VerifyDelegatedAccessListener.name);

  public constructor(
    private readonly verifyDelegatedAccessCommand: VerifyDelegatedAccessCommand,
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
    const event = VerifyDelegatedAccessEventDto.parse(payload);
    this.logger.log({ msg: 'Delegated access verification event received', type: event.type });
    await this.verifyDelegatedAccessCommand.run({ pipelineId: event.payload.pipelineId });
  }
}
