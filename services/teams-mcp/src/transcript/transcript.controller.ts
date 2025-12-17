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
import { OnEvent } from '@nestjs/event-emitter';
import { TraceService } from 'nestjs-otel';
import { DEAD_EXCHANGE, MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { wrapErrorHandlerOTEL } from '~/amqp/amqp.utils';
import { UserUpsertEvent } from '~/auth/events';
import { ValidationCallInterceptor } from '~/utils/validation-call.interceptor';
import {
  ChangeEventDto,
  ChangeNotificationCollectionDto,
  LifecycleChangeNotificationCollectionDto,
  LifecycleEventDto,
} from './transcript.dtos';
import { TranscriptService } from './transcript.service';

@Controller('transcript')
export class TranscriptController {
  private readonly logger = new Logger(TranscriptController.name);

  public constructor(
    private readonly transcriptService: TranscriptService,
    private readonly trace: TraceService,
  ) {}

  @Post('lifecycle')
  @HttpCode(HttpStatus.ACCEPTED)
  @UseInterceptors(ValidationCallInterceptor)
  public async lifecycle(@Body() event: LifecycleChangeNotificationCollectionDto) {
    this.logger.log({ event }, 'lifecycle notification!');

    const span = this.trace.getSpan();
    const reauthorizationRequests = event.value
      .filter((notification) => {
        const isTrusted = this.transcriptService.isWebhookTrustedViaState(notification.clientState);
        if (!isTrusted) {
          span?.addEvent('lifecycle notification invalid');
          this.logger.warn(
            { lifecycleNotification: notification },
            'lifecycle notification was discarded because of an invalid state',
          );
        }
        return isTrusted;
      })
      .map((notification) => {
        switch (notification.lifecycleEvent) {
          case 'subscriptionRemoved': {
            return this.transcriptService.enqueueSubscriptionRemoved(notification.subscriptionId);
          }
          case 'reauthorizationRequired': {
            return this.transcriptService.enqueueReauthorizationRequired(notification.subscriptionId);
          }

          default: {
            span?.addEvent('lifecycle notification unsupported', {
              type: notification.lifecycleEvent,
            });
            this.logger.warn(
              { lifecycleNotification: notification },
              `lifecycle notification was discarded because of an unsupported type: ${notification.lifecycleEvent}`,
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
      `notifications published: ${successful.length} successful, ${failed.length} failed`,
    );

    // NOTE: if we fail any, we reject this webhook as microsoft will send this again later
    if (failed.length > 0) {
      failed.forEach((fail) => {
        this.logger.warn({ error: fail.reason }, 'publishing reauthorization failed');
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
    this.logger.log({ event }, 'change notification!');

    const span = this.trace.getSpan();
    const processRequests = event.value
      .filter((notification) => {
        const isTrusted = this.transcriptService.isWebhookTrustedViaState(notification.clientState);
        if (!isTrusted) {
          span?.addEvent('change notification invalid');
          this.logger.warn(
            { changeNotification: notification },
            'change notification was discarded because of an invalid state',
          );
        }
        return isTrusted;
      })
      .map((notification) => {
        switch (notification.changeType) {
          case 'created': {
            return this.transcriptService.enqueueCreated(notification.subscriptionId, notification.resource);
          }

          default: {
            span?.addEvent('change notification unsupported', { type: notification.changeType });
            this.logger.warn(
              { changeNotification: notification },
              `change notification was discarded because of an unsupported type: ${notification.changeType}`,
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
      `notifications published: ${successful.length} successful, ${failed.length} failed`,
    );

    // NOTE: if we fail any, we reject this webhook as microsoft will send this again later
    if (failed.length > 0) {
      failed.forEach((fail) => {
        this.logger.warn({ error: fail.reason }, 'publishing process request failed');
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
    queue: 'unique.teams-mcp.transcript.lifecycle-notifications',
    routingKey: ['unique.teams-mcp.transcript.lifecycle-notification.*'],
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
    this.logger.log({ event }, 'lifecycle event!');

    switch (event.type) {
      case 'unique.teams-mcp.transcript.lifecycle-notification.subscription-requested': {
        return this.transcriptService.subscribe(event.userProfileId);
      }
      case 'unique.teams-mcp.transcript.lifecycle-notification.subscription-removed': {
        return this.transcriptService.remove(event.subscriptionId);
      }
      case 'unique.teams-mcp.transcript.lifecycle-notification.reauthorization-required': {
        return this.transcriptService.reauthorize(event.subscriptionId);
      }

      default:
        this.logger.warn(`event ${event.type} is unsupported`);
        break;
    }
  }

  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    queue: 'unique.teams-mcp.transcript.change-notifications',
    routingKey: ['unique.teams-mcp.transcript.change-notification.*'],
    createQueueIfNotExists: true,
    queueOptions: {
      deadLetterExchange: DEAD_EXCHANGE.name,
    },
    errorHandler: wrapErrorHandlerOTEL(defaultNackErrorHandler),
  })
  public async onChangeNotification(
    // @RabbitPayload(new ZodValidationPipe(ChangeEventDto)) event: ChangeEventDto,
    @RabbitPayload() payload: unknown,
  ) {
    const event = await ChangeEventDto.parseAsync(payload);
    this.logger.log({ event }, 'change event!');

    switch (event.type) {
      case 'unique.teams-mcp.transcript.change-notification.created': {
        return this.transcriptService.created(event.subscriptionId, event.resource);
      }

      default:
        this.logger.warn(`event ${event.type} is unsupported`);
        break;
    }
  }

  @OnEvent('user.upsert')
  public async userUpsert(payload: unknown) {
    const event = UserUpsertEvent.parse(payload);
    this.logger.debug({ event }, 'user upsert event!');

    return this.transcriptService.enqueueSubscriptionRequested(event.id);
  }
}
