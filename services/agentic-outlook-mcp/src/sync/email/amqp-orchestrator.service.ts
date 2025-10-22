import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { context, ROOT_CONTEXT, SpanStatusCode, trace } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../drizzle';
import { addSpanEvent } from '../../utils/add-span-event';
import {
  EmbeddingCompletedMessage,
  EmbeddingFailedMessage,
  EmbeddingRequestedMessage,
  IngestCompletedMessage,
  IngestFailedMessage,
  IngestRequestedMessage,
  OrchestratorEventType,
  OrchestratorMessage,
  ProcessingCompletedMessage,
  ProcessingFailedMessage,
  ProcessingRequestedMessage,
} from './orchestrator.messages';
import { RetryService } from './retry.service';
import { TracePropagationService } from './trace-propagation.service';

@Injectable()
export class AmqpOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly tracePropagation: TracePropagationService,
    private readonly retryService: RetryService,
  ) {}

  /**
   * Starts a new pipeline by creating the root trace and publishing the first event
   */
  public async startPipeline(
    userProfileId: string,
    folderId: string,
    emailId: string,
    message: Message,
  ): Promise<void> {
    const rootSpan = this.tracePropagation.startPipelineRootSpan(emailId, userProfileId);

    await context.with(trace.setSpan(ROOT_CONTEXT, rootSpan), async () => {
      try {
        const headers = this.tracePropagation.injectTraceContext(emailId);

        await this.amqpConnection.publish(
          'email.orchestrator',
          'orchestrator',
          {
            eventType: OrchestratorEventType.IngestRequested,
            userProfileId,
            folderId,
            emailId,
            timestamp: new Date().toISOString(),
            message,
          },
          { headers },
        );

        addSpanEvent(rootSpan, 'pipeline.started');
      } finally {
        rootSpan.end();
      }
    });
  }

  @RabbitSubscribe({
    exchange: 'email.orchestrator',
    routingKey: 'orchestrator',
    queue: 'q.orchestrator',
  })
  public async handleOrchestratorEvent(message: OrchestratorMessage, amqpMessage: ConsumeMessage) {
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);
    const traceHeaders = this.tracePropagation.extractTraceHeaders(amqpMessage);

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      `orchestrator.${message.eventType}`,
      {
        'event.type': message.eventType,
        'email.id': message.emailId,
        'user.id': message.userProfileId,
        'pipeline.step': 'orchestrator',
        attempt: attempt,
      },
      async (span) => {
        if (attempt > 1) {
          this.logger.log({
            msg: 'Retrying orchestrator event',
            eventType: message.eventType,
            emailId: message.emailId,
            attempt,
          });
          addSpanEvent(span, 'retry', { attempt });
        }

        try {
          switch (message.eventType) {
            case OrchestratorEventType.IngestRequested:
              await this.handleIngestRequested(message, traceHeaders);
              break;
            case OrchestratorEventType.IngestCompleted:
              await this.handleIngestCompleted(message, traceHeaders);
              break;
            case OrchestratorEventType.IngestFailed:
              await this.handleIngestFailed(message, traceHeaders);
              break;
            case OrchestratorEventType.ProcessingRequested:
              await this.handleProcessingRequested(message, traceHeaders);
              break;
            case OrchestratorEventType.ProcessingCompleted:
              await this.handleProcessingCompleted(message, traceHeaders);
              break;
            case OrchestratorEventType.ProcessingFailed:
              await this.handleProcessingFailed(message, traceHeaders);
              break;
            case OrchestratorEventType.EmbeddingRequested:
              await this.handleEmbeddingRequested(message, traceHeaders);
              break;
            case OrchestratorEventType.EmbeddingCompleted:
              await this.handleEmbeddingCompleted(message, traceHeaders);
              break;
            case OrchestratorEventType.EmbeddingFailed:
              await this.handleEmbeddingFailed(message, traceHeaders);
              break;
          }

          span.setStatus({ code: SpanStatusCode.OK });
        } catch (error) {
          span.setStatus({ code: SpanStatusCode.ERROR });
          await this.retryService.handleError({
            message,
            amqpMessage,
            error,
            retryExchange: 'email.orchestrator',
            retryRoutingKey: 'orchestrator.retry',
            onMaxRetriesExceeded: async () => {
              this.logger.error({
                msg: 'Failed to handle orchestrator event after max retries',
                eventType: message.eventType,
                emailId: message.emailId,
                error,
              });
            },
          });
          throw error;
        }
      },
    );
  }

  private async handleIngestRequested(
    message: IngestRequestedMessage,
    traceHeaders: Record<string, unknown>,
  ) {
    const { userProfileId, emailId, folderId, message: emailMessage } = message;

    await this.amqpConnection.publish(
      'email.pipeline',
      'email.ingest',
      {
        message: emailMessage,
        userProfileId,
        emailId,
        folderId,
      },
      { headers: traceHeaders },
    );
  }

  private async handleIngestCompleted(
    message: IngestCompletedMessage,
    traceHeaders: Record<string, unknown>,
  ) {
    const { userProfileId, emailId } = message;

    this.logger.debug({
      msg: 'Ingest completed',
      emailId,
      userProfileId,
    });

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'ingested',
        ingestionLastAttemptAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));

    await this.publishEvent(
      {
        eventType: OrchestratorEventType.ProcessingRequested,
        userProfileId,
        emailId,
        timestamp: new Date().toISOString(),
      },
      traceHeaders,
    );
  }

  private async handleIngestFailed(
    message: IngestFailedMessage,
    _traceHeaders: Record<string, unknown>,
  ) {
    const { messageId, error } = message;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'failed',
        ingestionLastError: error,
        ingestionLastAttemptAt: new Date().toISOString(),
        ingestionCompletedAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.messageId, messageId));
  }

  private async handleProcessingRequested(
    message: ProcessingRequestedMessage,
    traceHeaders: Record<string, unknown>,
  ) {
    const { userProfileId, emailId } = message;

    await this.amqpConnection.publish(
      'email.pipeline',
      'email.process',
      {
        userProfileId,
        emailId,
      },
      { headers: traceHeaders },
    );
  }

  private async handleProcessingCompleted(
    message: ProcessingCompletedMessage,
    traceHeaders: Record<string, unknown>,
  ) {
    const { userProfileId, emailId } = message;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'processed',
        ingestionLastAttemptAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));

    await this.publishEvent(
      {
        eventType: OrchestratorEventType.EmbeddingRequested,
        userProfileId,
        emailId,
        timestamp: new Date().toISOString(),
      },
      traceHeaders,
    );
  }

  private async handleProcessingFailed(
    message: ProcessingFailedMessage,
    _traceHeaders: Record<string, unknown>,
  ) {
    const { emailId, error } = message;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'failed',
        ingestionLastError: error,
        ingestionLastAttemptAt: new Date().toISOString(),
        ingestionCompletedAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));
  }

  private async handleEmbeddingRequested(
    message: EmbeddingRequestedMessage,
    traceHeaders: Record<string, unknown>,
  ) {
    const { userProfileId, emailId } = message;

    await this.amqpConnection.publish(
      'email.pipeline',
      'email.embed',
      {
        userProfileId,
        emailId,
      },
      { headers: traceHeaders },
    );
  }

  private async handleEmbeddingCompleted(
    message: EmbeddingCompletedMessage,
    _traceHeaders: Record<string, unknown>,
  ) {
    const { emailId } = message;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'embedded',
        ingestionLastAttemptAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));

    // For now, this is the end of the pipeline
  }

  private async handleEmbeddingFailed(
    message: EmbeddingFailedMessage,
    _traceHeaders: Record<string, unknown>,
  ) {
    const { emailId, error } = message;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'failed',
        ingestionLastError: error,
        ingestionLastAttemptAt: new Date().toISOString(),
        ingestionCompletedAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));
  }

  public async publishEvent(
    event: OrchestratorMessage,
    traceHeaders: Record<string, unknown>,
  ): Promise<void> {
    await this.amqpConnection.publish('email.orchestrator', 'orchestrator', event, {
      headers: traceHeaders,
    });
  }
}
