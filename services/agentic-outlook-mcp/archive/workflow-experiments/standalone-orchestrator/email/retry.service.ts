import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { ConsumeMessage } from 'amqplib';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../../utils/normalize-error';
import { FatalPipelineError } from './pipeline.errors';
import { TracePropagationService } from './trace-propagation.service';

export interface RetryOptions<TMessage> {
  message: TMessage;
  amqpMessage: ConsumeMessage;
  error: unknown;
  retryExchange: string;
  retryRoutingKey: string;
  onMaxRetriesExceeded?: (
    message: TMessage,
    error: string,
    traceHeaders: Record<string, unknown>,
  ) => Promise<void>;
}

@Injectable()
export class RetryService {
  private readonly logger = new Logger(this.constructor.name);

  private readonly MAX_ATTEMPTS = 6;
  private readonly BASE_DELAY_MS = 30_000; // 30 seconds
  private readonly MIN_DELAY_MS = 15_000; // clamp floor
  private readonly MAX_DELAY_MS = 30 * 60_000; // 30 minutes cap
  private readonly JITTER_RATIO = 0.2; // ±20%

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    private readonly tracePropagation: TracePropagationService,
  ) {}

  public async handleError<TMessage>(options: RetryOptions<TMessage>): Promise<void> {
    const { message, amqpMessage, error, retryExchange, retryRoutingKey, onMaxRetriesExceeded } =
      options;
    const traceHeaders = this.tracePropagation.extractTraceHeaders(amqpMessage);

    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);
    const serializedError = serializeError(normalizeError(error));

    this.logger.error({
      msg: 'Operation failed',
      message,
      attempt,
      error: serializedError,
    });

    if (error instanceof FatalPipelineError) {
      this.logger.error({
        msg: 'Fatal error encountered, not retrying',
        error: serializedError,
      });
      if (onMaxRetriesExceeded)
        await onMaxRetriesExceeded(message, JSON.stringify(serializedError), traceHeaders);
      return;
    }

    if (attempt >= this.MAX_ATTEMPTS) {
      this.logger.error({
        msg: 'Max attempts reached',
        attempt,
        maxAttempts: this.MAX_ATTEMPTS,
        error: serializedError,
      });
      if (onMaxRetriesExceeded)
        await onMaxRetriesExceeded(message, JSON.stringify(serializedError), traceHeaders);
      return;
    }

    const delayMs = this.computeDelayMs(attempt);

    this.logger.log({
      msg: 'Retrying operation',
      nextAttempt: attempt + 1,
      delayMs,
      retryRoutingKey,
    });

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
