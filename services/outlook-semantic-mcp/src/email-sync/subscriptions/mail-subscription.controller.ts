import {
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
import { TraceService } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { normalizeError } from '~/utils/normalize-error';
import { ValidationCallInterceptor } from '~/utils/validation-call.interceptor';
import {
  ChangeNotificationCollectionDto,
  LifecycleChangeNotificationCollectionDto,
  LifecycleEventDto,
} from './subscription.dtos';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import { MailSubscriptionUtilsService } from './subscription-utils.service';

@Controller('mail-subscription')
export class MailSubscriptionController {
  private readonly logger = new Logger(MailSubscriptionController.name);

  public constructor(
    private readonly subscriptionCreate: SubscriptionCreateService,
    private readonly subscriptionReauthorize: SubscriptionReauthorizeService,
    private readonly subscriptionRemove: SubscriptionRemoveService,
    private readonly utils: MailSubscriptionUtilsService,
    private readonly trace: TraceService,
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

    const span = this.trace.getSpan();
    const reauthorizationRequests = event.value
      .filter((notification) => {
        const isTrusted = this.utils.isWebhookTrustedViaState(notification.clientState);
        if (!isTrusted) {
          span?.addEvent('lifecycle notification invalid');
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
            span?.addEvent('lifecycle notification unsupported', {
              type: notification.lifecycleEvent,
            });
            this.logger.warn(
              { lifecycleNotification: notification, eventType: notification.lifecycleEvent },
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

    span?.addEvent('notifications published', {
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
        this.logger.warn(
          { error: serializeError(normalizeError(fail.reason)) },
          'Failed to publish reauthorization event to message queue',
        );
        // span?.recordException(fail.reason)
      });
      throw new InternalServerErrorException(
        { errors: failed.map((v) => v.reason) },
        { description: `internal publishing of ${failed.length} messages failed` },
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

    const span = this.trace.getSpan();
    const processRequests = event.value
      .filter((notification) => {
        const isTrusted = this.utils.isWebhookTrustedViaState(notification.clientState);
        if (!isTrusted) {
          span?.addEvent('change notification invalid');
          this.logger.warn(
            { changeNotification: notification },
            'Discarding change notification due to invalid authentication state',
          );
        }
        return isTrusted;
      })
      .map((notification) => {
        switch (notification.changeType) {
          case 'created': {
            // TOOD: Implement subscription created and full sync
            return null;
          }

          default: {
            span?.addEvent('change notification unsupported', { type: notification.changeType });
            this.logger.warn(
              { changeNotification: notification, changeType: notification.changeType },
              'Discarding change notification with unsupported change type',
            );
            return null;
          }
        }
      })
      // REVIEW: we could just leave the `null` values and then filter on `fulfilled` + `null` to see how many discarded
      .filter((v) => v !== null);

    const publishings = await Promise.allSettled(processRequests);
    const successful = publishings.filter((result) => result.status === 'fulfilled');
    const failed = publishings.filter((result) => result.status === 'rejected');

    span?.addEvent('notifications published', {
      successful: successful.length,
      failed: failed.length,
    });
    this.logger.log(
      { successful: successful.length, failed: failed.length },
      'Successfully processed all change notifications from Microsoft Graph',
    );

    // NOTE: if we fail any, we reject this webhook as microsoft will send this again later
    if (failed.length > 0) {
      failed.forEach((fail) => {
        this.logger.warn(
          { error: serializeError(normalizeError(fail.reason)) },
          'Failed to publish processing request to message queue',
        );
        // span?.recordException(fail.reason)
      });
      throw new InternalServerErrorException(
        { errors: failed.map((v) => v.reason) },
        { description: `internal publishing of ${failed.length} messages failed` },
      );
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
  public async onLifecycleNotification(
    // @RabbitPayload(new ZodValidationPipe(LifecycleEventDto)) event: LifecycleEventDto,
    @RabbitPayload() payload: unknown,
  ) {
    const event = await LifecycleEventDto.parseAsync(payload);
    this.logger.log({ event }, 'Processing lifecycle event from message queue');

    switch (event.type) {
      case 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-requested': {
        return this.subscriptionCreate.subscribe(event.userProfileId);
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
