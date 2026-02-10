import type { MessageErrorHandler } from '@golevelup/nestjs-rabbitmq';
import { SpanStatusCode, trace } from '@opentelemetry/api';
import type { Channel, ConsumeMessage } from 'amqplib';

/**
 * Record the error in the current span if active.
 *
 * @param handler RabbitMQ error handler function.
 * @returns Wrapped handler.
 */
export const wrapErrorHandlerOTEL = (handler: MessageErrorHandler) => {
  return (channel: Channel, msg: ConsumeMessage, err: unknown) => {
    const span = trace.getActiveSpan();
    if (span?.isRecording()) {
      const exception = err instanceof Error ? err : String(err);
      span.recordException(exception);
      span.setStatus({ code: SpanStatusCode.ERROR, message: exception.toString() });
    }
    return handler(channel, msg, err);
  };
};
