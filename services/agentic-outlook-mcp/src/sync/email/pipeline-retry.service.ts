import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { ConsumeMessage } from 'amqplib';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../../utils/normalize-error';
import { FatalPipelineError } from './pipeline.errors';
import { TracePropagationService } from './trace-propagation.service';

export interface RetryHandlerOptions<TMessage, TFailedEvent> {
  message: TMessage;
  amqpMessage: ConsumeMessage;
  error: unknown;
  retryExchange: string;
  retryRoutingKey: string;
  failedEventName: string;
  createFailedEvent: (serializedError: string) => TFailedEvent;
}

@Injectable()
export class PipelineRetryService {
  private readonly logger = new Logger(this.constructor.name);

  private readonly MAX_ATTEMPTS = 6;
  private readonly BASE_DELAY_MS = 30_000; // 30 seconds
  private readonly MIN_DELAY_MS = 15_000; // clamp floor
  private readonly MAX_DELAY_MS = 30 * 60_000; // 30 minutes cap
  private readonly JITTER_RATIO = 0.2; // ±20%

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    private readonly eventEmitter: EventEmitter2,
    private readonly tracePropagation: TracePropagationService,
  ) {}

  public async handlePipelineError<TMessage, TFailedEvent>(
    options: RetryHandlerOptions<TMessage, TFailedEvent>,
  ): Promise<void> {
    const {
      message,
      amqpMessage,
      error,
      retryExchange,
      retryRoutingKey,
      failedEventName,
      createFailedEvent,
    } = options;

    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);
    const serializedError = serializeError(normalizeError(error));

    this.logger.error({
      msg: 'Pipeline step failed',
      message,
      attempt,
      error: serializedError,
    });

    if (error instanceof FatalPipelineError) {
      this.logger.error({
        msg: 'Fatal error encountered, not retrying',
        error: serializedError,
      });
      this.eventEmitter.emit(failedEventName, createFailedEvent(JSON.stringify(serializedError)));
      return;
    }

    if (attempt >= this.MAX_ATTEMPTS) {
      this.eventEmitter.emit(failedEventName, createFailedEvent(JSON.stringify(serializedError)));
      return;
    }

    const delayMs = this.computeDelayMs(attempt);
    const traceHeaders = this.tracePropagation.extractTraceHeaders(amqpMessage);
    await this.amqpConnection.publish(retryExchange, retryRoutingKey, message, {
      expiration: delayMs,
      headers: { ...traceHeaders, 'x-attempt': attempt + 1 },
    });
  }

  private computeDelayMs(attempt: number): number {
    const exp = 2 ** Math.max(0, attempt - 1);
    const base = Math.min(this.MAX_DELAY_MS, Math.max(this.MIN_DELAY_MS, this.BASE_DELAY_MS * exp));
    const jitter = 1 + (Math.random() * 2 - 1) * this.JITTER_RATIO; // 0.8..1.2 if 20%
    return Math.floor(base * jitter);
  }
}
