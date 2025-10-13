import { RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { ConsumeMessage } from 'amqplib';
import { and, eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../../drizzle';
import { PipelineEvents, ProcessFailedEvent, ProcessingCompletedEvent } from '../pipeline.events';
import { PipelineRetryService } from '../pipeline-retry.service';

interface ProcessMessage {
  userProfileId: string;
  emailId: string;
}

@Injectable()
export class ProcessService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
    private readonly pipelineRetryService: PipelineRetryService,
  ) {}

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.process',
    queue: 'q.email.process',
  })
  public async process(processMessage: ProcessMessage, amqpMessage: ConsumeMessage) {
    const { userProfileId, emailId } = processMessage;
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    if (attempt > 1) {
      this.logger.log({
        msg: 'Retrying process for email',
        emailId,
        attempt,
      });
    }

    try {
      const email = await this.db.query.emails.findFirst({
        where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
      });

      if (!email) {
        this.logger.warn('Email not found, skipping processing');
        return;
      }

      // TODO: Implement processing logic

      this.logger.debug({
        msg: 'Processing...',
        emailId: emailId,
        userProfileId: userProfileId,
      });

      this.eventEmitter.emit(
        PipelineEvents.ProcessingCompleted,
        new ProcessingCompletedEvent(
          TypeID.fromString(userProfileId, 'user_profile'),
          TypeID.fromString(emailId, 'email'),
        ),
      );

      return;
    } catch (error) {
      await this.pipelineRetryService.handlePipelineError({
        message: processMessage,
        amqpMessage,
        error,
        retryExchange: 'email.pipeline.retry',
        retryRoutingKey: 'email.process.retry',
        failedEventName: PipelineEvents.ProcessFailed,
        createFailedEvent: (serializedError) =>
          new ProcessFailedEvent(
            TypeID.fromString(userProfileId, 'user_profile'),
            emailId,
            serializedError,
          ),
      });
    }
  }
}
