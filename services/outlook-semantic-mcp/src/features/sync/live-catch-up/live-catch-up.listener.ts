import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { AppConfig, appConfig } from '~/config';
import { LiveCatchUpCommand } from './live-catch-up.command';
import { LiveCatchUpEventDto } from './live-catch-up-event.dto';

@Injectable()
export class LiveCatchUpListener {
  private readonly logger = new Logger(LiveCatchUpListener.name);

  public constructor(
    private readonly liveCatchUpCommand: LiveCatchUpCommand,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.live-catch-up',
    routingKey: ['unique.outlook-semantic-mcp.live-catch-up.*'],
    createQueueIfNotExists: true,
    queueOptions: { deadLetterExchange: DEAD_EXCHANGE.name },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onLiveCatchUpEvent(@RabbitPayload() payload: unknown): Promise<void> {
    const event = LiveCatchUpEventDto.parse(payload);
    this.logger.log({ msg: 'Live catch-up event received', type: event.type });
    switch (event.type) {
      case 'unique.outlook-semantic-mcp.live-catch-up.execute': {
        return await this.liveCatchUpCommand.run({
          ...event.payload,
          liveCatchupOverlappingWindow: this.config.liveCatchupOverlappingWindowMinutes,
        });
      }
      case 'unique.outlook-semantic-mcp.live-catch-up.ready-recheck': {
        return await this.liveCatchUpCommand.run({
          ...event.payload,
          liveCatchupOverlappingWindow: this.config.liveCatchupRecheckOverlappingWindowMinutes,
        });
      }
      default: {
        this.logger.error({ msg: `Unsuported live catchup event type: ${JSON.stringify(event)}` });
      }
    }
  }
}
