import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { UserAuthorizedEventDto } from '~/auth/dtos/user-authorized-event.dto';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SubscriptionCreateService } from '../subscription-create.service';

@Injectable()
export class PostAuthorizationListener {
  private readonly logger = new Logger(PostAuthorizationListener.name);

  public constructor(private readonly subscriptionCreateService: SubscriptionCreateService) {}

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.auth.post-authorization',
    routingKey: ['unique.outlook-semantic-mcp.auth.user-authorized'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  @Span()
  public async onUserAuthorized(@RabbitPayload() payload: unknown): Promise<void> {
    const event = UserAuthorizedEventDto.parse(payload);
    const { userProfileId } = event.payload;
    try {
      const result = await this.subscriptionCreateService.subscribe(
        convertUserProfileIdToTypeId(userProfileId),
      );
      this.logger.log({
        msg: 'Subscription outcome after user authorization',
        userProfileId,
        status: result.status,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to subscribe user after authorization',
        userProfileId,
        error,
      });
    }
  }
}
