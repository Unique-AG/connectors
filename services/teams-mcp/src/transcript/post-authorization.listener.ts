import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { UserAuthorizedEventDto } from '~/auth/dtos/user-authorized-event.dto';
import { type MicrosoftConfig, microsoftConfig } from '~/config';
import { normalizeError } from '~/utils/normalize-error';
import { SubscriptionCreateService } from './subscription-create.service';

@Injectable()
export class PostAuthorizationListener {
  private readonly logger = new Logger(PostAuthorizationListener.name);

  public constructor(
    @Inject(microsoftConfig.KEY) private readonly config: MicrosoftConfig,
    private readonly subscriptionCreate: SubscriptionCreateService,
  ) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.teams-mcp.auth.post-authorization',
    routingKey: ['unique.teams-mcp.auth.user-authorized'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onUserAuthorized(@RabbitPayload() payload: unknown): Promise<void> {
    const event = UserAuthorizedEventDto.parse(payload);
    const { userProfileId } = event.payload;

    if (!this.config.autoStartIngestion) {
      this.logger.debug(
        { userProfileId },
        'Auto-start ingestion is disabled, skipping subscription enqueue for authorized user',
      );
      return;
    }

    const tid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(tid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    try {
      await this.subscriptionCreate.enqueueSubscriptionRequested(userProfileTypeid);
      this.logger.log(
        { userProfileId },
        'Enqueued transcript subscription request after user authorization',
      );
    } catch (error) {
      this.logger.error({
        message: 'Failed to enqueue transcript subscription after user authorization',
        userProfileId,
        error: serializeError(normalizeError(error)),
      });
    }
  }
}
