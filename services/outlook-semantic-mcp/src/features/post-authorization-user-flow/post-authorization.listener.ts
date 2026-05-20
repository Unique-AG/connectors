import {
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { pick } from 'remeda';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { UserAuthorizedEventDto } from '~/auth/dtos/user-authorized-event.dto';
import { AppConfig, appConfig, McpBackendType } from '~/config';
import { IsInboxDeletingQuery } from '~/features/delete-inbox/is-inbox-deleting.query';
import { NewTrace } from '~/features/tracing.utils';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { SubscriptionCreateService } from '../subscriptions/subscription-create.service';

@Injectable()
export class PostAuthorizationListener {
  private readonly logger = new Logger(PostAuthorizationListener.name);

  public constructor(
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    private readonly subscriptionCreateService: SubscriptionCreateService,
    private readonly isInboxDeleting: IsInboxDeletingQuery,
  ) {}

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
  @NewTrace('amqp.post-authorization')
  public async onUserAuthorized(@RabbitPayload() payload: unknown): Promise<void> {
    const event = UserAuthorizedEventDto.parse(payload);
    const { userProfileId } = event.payload;

    const handleByMcpBackend: Record<McpBackendType, () => Promise<void>> = {
      [McpBackendType.MicrosoftGraph]: () => this.handleForMicrosoftGraphBackend(userProfileId),
      [McpBackendType.MicrosoftGraphAndUniqueApi]: () =>
        this.handleForMicrosoftGraphAndUniqueApi(userProfileId),
    };

    await handleByMcpBackend[this.config.mcpBackend]();
  }

  private async handleForMicrosoftGraphBackend(userProfileId: string): Promise<void> {
    await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(userProfileId));
  }

  private async handleForMicrosoftGraphAndUniqueApi(userProfileId: string): Promise<void> {
    if (await this.isInboxDeleting.run(userProfileId)) {
      this.logger.warn({
        userProfileId,
        msg: 'Inbox deletion in progress, skipping post-authorization subscription',
      });
      return;
    }

    try {
      const result = await this.subscriptionCreateService.subscribe(
        convertUserProfileIdToTypeId(userProfileId),
      );
      this.logger.log({
        msg: 'Subscription outcome after user authorization',
        userProfileId,
        ...pick(result, ['status', 'reason']),
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
