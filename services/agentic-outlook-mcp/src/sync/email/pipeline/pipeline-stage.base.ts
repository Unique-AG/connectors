import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { startObservation } from '@langfuse/tracing';
import { Logger } from '@nestjs/common';
import { Span, SpanStatusCode } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { addSpanEvent } from '../../../utils/add-span-event';
import { OrchestratorEventType } from '../orchestrator.messages';
import { RetryService } from '../retry.service';
import { TracePropagationService } from '../trace-propagation.service';

export interface PipelineStageConfig {
  spanName: string;
  retryRoutingKey: string;
  successEvent: OrchestratorEventType;
  failureEvent: OrchestratorEventType;
}

export abstract class PipelineStageBase<TMessage> {
  protected abstract readonly logger: Logger;
  protected abstract readonly config: PipelineStageConfig;
  
  protected constructor(
    protected readonly amqpConnection: AmqpConnection,
    protected readonly retryService: RetryService,
    protected readonly tracePropagation: TracePropagationService,
  ) {}

  protected async executeStage(
    message: TMessage,
    amqpMessage: ConsumeMessage,
    attributes: Record<string, unknown>,
  ): Promise<void> {
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      this.config.spanName,
      {
        ...attributes,
        attempt,
      },
      async (span) => {
        if (attempt > 1) {
          this.handleRetry(message, attempt, span);
        }

        try {
          const result = await this.processMessage(message, amqpMessage, span);
          
          span.setStatus({ code: SpanStatusCode.OK });
          
          await this.publishSuccessEvent(message, amqpMessage, result);
        } catch (error) {
          await this.handleError(message, amqpMessage, span, error);
        }
      },
    );
  }

  protected abstract processMessage(
    message: TMessage,
    amqpMessage: ConsumeMessage,
    span: Span,
  ): Promise<unknown>;

  protected abstract getMessageIdentifiers(message: TMessage): {
    userProfileId: string;
    emailId?: string;
    [key: string]: unknown;
  };

  protected abstract buildSuccessPayload(
    message: TMessage,
    additionalData?: unknown,
  ): Record<string, unknown>;

  protected abstract buildFailurePayload(
    message: TMessage,
    error: string,
  ): Record<string, unknown>;

  private handleRetry(message: TMessage, attempt: number, span: Span): void {
    const identifiers = this.getMessageIdentifiers(message);
    this.logger.log({
      msg: `Retrying ${this.config.spanName} stage`,
      ...identifiers,
      attempt,
    });
    addSpanEvent(span, 'retry', { attempt });
  }

  private async publishSuccessEvent(
    message: TMessage,
    amqpMessage: ConsumeMessage,
    additionalData?: unknown,
  ): Promise<void> {
    const traceHeaders = this.tracePropagation.extractTraceHeaders(amqpMessage);
    const payload = this.buildSuccessPayload(message, additionalData);
    
    await this.amqpConnection.publish(
      'email.orchestrator',
      'orchestrator',
      {
        eventType: this.config.successEvent,
        ...payload,
        timestamp: new Date().toISOString(),
      },
      { headers: traceHeaders },
    );
  }

  private extractErrorChain(error: unknown): Array<{
    name: string;
    message: string;
    stack?: string;
  }> {
    const chain: Array<{ name: string; message: string; stack?: string }> = [];
    let currentError: unknown = error;
    
    while (currentError) {
      if (currentError instanceof Error) {
        chain.push({
          name: currentError.name,
          message: currentError.message,
          stack: currentError.stack,
        });
        currentError = 'cause' in currentError ? currentError.cause : undefined;
      } else {
        chain.push({
          name: 'Error',
          message: String(currentError),
        });
        break;
      }
    }
    
    return chain;
  }

  private async handleError(
    message: TMessage,
    amqpMessage: ConsumeMessage,
    span: Span,
    error: unknown,
  ): Promise<void> {
    const errorChain = this.extractErrorChain(error);
    const rootError = errorChain[0];
    const identifiers = this.getMessageIdentifiers(message);
    
    span.setStatus({
      code: SpanStatusCode.ERROR,
      message: rootError?.message,
    });
    span.recordException(error as Error);
    
    const spanAttributes: Record<string, string> = {
      'error.type': rootError?.name || '',
      'error.message': rootError?.message || '',
      'error.stack': rootError?.stack || '',
    };
    
    errorChain.forEach((err, index) => {
      if (index === 0) return;
      
      const prefix = index === 1 ? 'error.cause' : `error.cause.${index - 1}`;
      spanAttributes[`${prefix}.type`] = err.name;
      spanAttributes[`${prefix}.message`] = err.message;
      if (err.stack) {
        spanAttributes[`${prefix}.stack`] = err.stack;
      }
    });
    
    span.setAttributes(spanAttributes);
    
    const errorDetails: Record<string, unknown> = {
      ...identifiers,
      errorChain: errorChain.map((err, index) => ({
        level: index,
        type: err.name,
        message: err.message,
        stack: err.stack,
      })),
    };
    
    startObservation(
      'error',
      {
        statusMessage: rootError?.message,
        level: 'ERROR',
        metadata: errorDetails,
      },
      { asType: 'event', parentSpanContext: span.spanContext() },
    ).end();
  
    
    await this.retryService.handleError({
      message,
      amqpMessage,
      error,
      retryExchange: 'email.pipeline.retry',
      retryRoutingKey: this.config.retryRoutingKey,
      onMaxRetriesExceeded: async (_msg, errorStr, traceHeaders) => {
        const payload = this.buildFailurePayload(message, errorStr);
        
        await this.amqpConnection.publish(
          'email.orchestrator',
          'orchestrator',
          {
            eventType: this.config.failureEvent,
            ...payload,
            timestamp: new Date().toISOString(),
            error: errorStr,
            errorType: rootError?.name,
            errorChain: errorChain.map(err => ({
              type: err.name,
              message: typeof err.message === 'object' ? JSON.stringify(err.message) : err.message,
            })),
          },
          { headers: traceHeaders },
        );
      },
    });
  }
}
