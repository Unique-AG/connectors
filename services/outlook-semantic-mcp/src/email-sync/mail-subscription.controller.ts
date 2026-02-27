import assert from 'node:assert';
import {
  AmqpConnection,
  defaultNackErrorHandler,
  RabbitPayload,
  RabbitSubscribe,
} from '@golevelup/nestjs-rabbitmq';
import {
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  InternalServerErrorException,
  Logger,
  Post,
  UseInterceptors,
} from '@nestjs/common';
import { partition } from 'remeda';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { traceAttrs, traceError, traceEvent } from '~/email-sync/tracing.utils';
import { ValidationCallInterceptor } from '~/utils/validation-call.interceptor';
import { FullSyncCommand } from './full-sync/full-sync.command';
import { MessageEventDto } from './mail-ingestion/dtos/message-event.dto';
import { IngestionPriority } from './mail-ingestion/utils/ingestion-queue.utils';
import {
  ChangeNotificationCollectionDto,
  LifecycleChangeNotificationCollectionDto,
  LifecycleEventDto,
} from './subscriptions/subscription.dtos';
import { SubscriptionReauthorizeService } from './subscriptions/subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscriptions/subscription-remove.service';
import { MailSubscriptionUtilsService } from './subscriptions/subscription-utils.service';

@Controller('mail-subscription')
export class MailSubscriptionController {
  private readonly logger = new Logger(MailSubscriptionController.name);

  public constructor(
    private readonly subscriptionReauthorize: SubscriptionReauthorizeService,
    private readonly subscriptionRemove: SubscriptionRemoveService,
    private readonly utils: MailSubscriptionUtilsService,
    private readonly amqpConnection: AmqpConnection,
    private readonly fullSyncCommand: FullSyncCommand,
  ) {}

  @Post('lifecycle')
  @HttpCode(HttpStatus.ACCEPTED)
  @UseInterceptors(ValidationCallInterceptor)
  public async lifecycle(@Body() event: LifecycleChangeNotificationCollectionDto) {
    this.logger.log(
      {
        notificationCount: event.value.length,
        eventSource: 'microsoft_graph',
        webhookType: 'lifecycle',
      },
      'Received lifecycle notification webhook from Microsoft Graph',
    );

    const reauthorizationRequests = event.value
      .filter((notification) => {
        const isTrusted = this.utils.isWebhookTrustedViaState(notification.clientState);
        if (!isTrusted) {
          traceEvent('lifecycle notification invalid');
          this.logger.warn(
            { lifecycleNotification: notification },
            'Discarding lifecycle notification due to invalid authentication state',
          );
        }
        return isTrusted;
      })
      .map((notification) => {
        switch (notification.lifecycleEvent) {
          case 'subscriptionRemoved': {
            return this.subscriptionRemove.enqueueSubscriptionRemoved(notification.subscriptionId);
          }
          case 'reauthorizationRequired': {
            return this.subscriptionReauthorize.enqueueReauthorizationRequired(
              notification.subscriptionId,
            );
          }

          default: {
            traceEvent('lifecycle notification unsupported', {
              type: notification.lifecycleEvent,
            });
            this.logger.warn(
              {
                lifecycleNotification: notification,
                eventType: notification.lifecycleEvent,
              },
              'Discarding lifecycle notification with unsupported event type',
            );
            return null;
          }
        }
      })
      // REVIEW: we could just leave the `null` values and then filter on `fulfilled` + `null` to see how many discarded
      .filter((v) => v !== null);

    const publishings = await Promise.allSettled(reauthorizationRequests);
    const successful = publishings.filter((result) => result.status === 'fulfilled');
    const failed = publishings.filter((result) => result.status === 'rejected');

    traceEvent('notifications published', {
      successful: successful.length,
      failed: failed.length,
    });
    this.logger.log(
      { successful: successful.length, failed: failed.length },
      'Successfully processed all lifecycle notifications from Microsoft Graph',
    );

    // NOTE: if we fail any, we reject this webhook as microsoft will send this again later
    if (failed.length > 0) {
      failed.forEach((fail) => {
        this.logger.warn({
          msg: 'Failed to publish reauthorization event to message queue',
          err: fail.reason,
        });
        traceError(fail.reason);
      });
      throw new InternalServerErrorException(
        { errors: failed.map((v) => v.reason) },
        {
          description: `internal publishing of ${failed.length} messages failed`,
        },
      );
    }
  }

  @Post('notification')
  @HttpCode(HttpStatus.ACCEPTED)
  @UseInterceptors(ValidationCallInterceptor)
  public async notification(@Body() event: ChangeNotificationCollectionDto) {
    this.logger.log(
      {
        notificationCount: event.value.length,
        eventSource: 'microsoft_graph',
        webhookType: 'change',
      },
      'Received change notification webhook from Microsoft Graph',
    );

    const [notificationsToIgnore, notificationsToProcess] = partition(
      event.value,
      (notification) => notification.changeType === 'deleted',
    );

    traceAttrs({
      notifications_to_process_count: notificationsToProcess.length,
      notifications_to_ignore_count: notificationsToIgnore.length,
    });

    if (!notificationsToProcess.length) {
      traceEvent('No notifications to process');
      return;
    }

    for (const notification of notificationsToProcess) {
      assert.ok(
        notification.resourceData,
        `Missing resource data from notification: ${JSON.stringify(notification)}`,
      );
      const payload = await MessageEventDto.encodeAsync({
        type: 'unique.outlook-semantic-mcp.mail-event.live-change-notification-received',
        payload: {
          subscriptionId: notification.subscriptionId,
          messageId: notification.resourceData.id,
        },
      });
      this.logger.log(`published, ${JSON.stringify(payload)}`);
      await this.amqpConnection.publish(MAIN_EXCHANGE.name, payload.type, payload, {
        priority: IngestionPriority.High,
      });
    }
  }

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.outlook-semantic-mcp.mail.lifecycle-notifications',
    routingKey: ['unique.outlook-semantic-mcp.mail.lifecycle-notification.*'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onLifecycleNotification(@RabbitPayload() payload: unknown) {
    const event = await LifecycleEventDto.parseAsync(payload);
    this.logger.log({ event }, 'Processing lifecycle event from message queue');

    switch (event.type) {
      case 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-created': {
        return this.fullSyncCommand.run(event.subscriptionId);
      }
      case 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-removed': {
        return this.subscriptionRemove.remove(event.subscriptionId);
      }
      case 'unique.outlook-semantic-mcp.mail.lifecycle-notification.reauthorization-required': {
        return this.subscriptionReauthorize.reauthorize(event.subscriptionId);
      }

      default:
        this.logger.warn(
          { eventType: event.type },
          'Received unsupported lifecycle event type and will ignore it',
        );
        break;
    }
  }
}
