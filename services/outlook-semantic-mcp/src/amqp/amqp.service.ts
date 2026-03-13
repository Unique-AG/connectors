import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, OnApplicationBootstrap } from '@nestjs/common';
import { context, propagation, ROOT_CONTEXT, SpanStatusCode } from '@opentelemetry/api';
import type { ConsumeMessage } from 'amqplib';
import { TraceService } from 'nestjs-otel';

@Injectable()
export class AMQPService implements OnApplicationBootstrap {
  public constructor(
    private readonly amqpConn: AmqpConnection,
    private readonly trace: TraceService,
  ) {}

  public onApplicationBootstrap() {
    this.patchAMQPPublishWithOTEL(this.amqpConn);
  }

  // NOTE: this should be done using @opentelemetry/instrumentation
  private patchAMQPPublishWithOTEL(amqpConn: AmqpConnection) {
    // Grab the prototype of the amqp connection instance so we can monkey-patch
    // its 'publish' method for all uses of this instance (the underlaying implementation uses a
    // static instance shared across every provider anyway, so `this` is safe).
    const proto = Object.getPrototypeOf(amqpConn);

    if (!proto.__OOBPublishErrorOtelPatched) {
      // Keep a bound reference to the original publish method so internal 'this' stays correct.
      // Without .bind(amqpConn), calling original later would lose context.
      const original: typeof amqpConn.publish = proto.publish.bind(amqpConn);

      // Our patched publish wraps the original to attach error instrumentation.
      const patched: typeof amqpConn.publish = async (...args) => {
        // Get the current OpenTelemetry span (if any) from our tracing service.
        // We want to correlate any out-of-band (OOB) connection errors with the
        // active span at the time publish is invoked.
        const span = this.trace.getSpan();

        const onError = (err: unknown) => {
          // If there's an active, recording span and the error is a real Error,
          // record it and mark the span as failed for better observability.
          if (span?.isRecording()) {
            const exception = err instanceof Error ? err : String(err);
            span.recordException(exception);
            span.setStatus({ code: SpanStatusCode.ERROR, message: exception.toString() });
          }
        };

        // Inject the current W3C trace context (traceparent/tracestate) into the
        // message headers so consumers can restore it and link their spans.
        const [exchange, routingKey, message, options = {}] = args as Parameters<
          typeof amqpConn.publish
        >;
        const headers: Record<string, unknown> = { ...(options?.headers ?? {}) };
        propagation.inject(context.active(), headers);
        const patchedArgs: Parameters<typeof amqpConn.publish> = [
          exchange,
          routingKey,
          message,
          { ...options, headers },
        ];

        // Listen once for a connection-level 'error' event.
        // Some AMQP errors may occur asynchronously (e.g., broker issues) and not
        // be thrown directly by the publish call; this captures those OOB errors.
        amqpConn.connection.once('error', onError);

        // Delegate to the original publish behavior with patched headers.
        return original(...patchedArgs).finally(() =>
          // Unregister the listener to prevent building them up over time.
          amqpConn.connection.removeListener('error', onError),
        );
      };

      // Swap the prototype method to our patched version so all subsequent
      // calls to amqpConn.publish go through our instrumentation.
      proto.publish = patched;

      // Patch wrapConsumer to extract W3C trace context from incoming message headers
      // and run each delivery inside that context. wrapConsumer is called once per
      // subscriber setup and wraps the amqplib channel.consume callback, so every
      // message goes through it before NestJS or any handler decorator touches it.
      // This allows @RabbitSpan() to simply create a child span of whatever context
      // is active — either the publisher's span (same trace) or ROOT_CONTEXT (new trace)
      // — without needing @RabbitRequest() on every listener method.
      proto.wrapConsumer = function (consumer: (msg: ConsumeMessage | null) => unknown) {
        return (msg: ConsumeMessage | null) => {
          const parentContext =
            msg != null
              ? propagation.extract(ROOT_CONTEXT, msg.properties?.headers ?? {})
              : ROOT_CONTEXT;
          const messageProcessingPromise = Promise.resolve(
            context.with(parentContext, () => consumer(msg)),
          );
          // biome-ignore lint/suspicious/noExplicitAny: internal tracking set
          (this as any).outstandingMessageProcessing.add(messageProcessingPromise);
          messageProcessingPromise.finally(() =>
            // biome-ignore lint/suspicious/noExplicitAny: internal tracking set
            (this as any).outstandingMessageProcessing.delete(messageProcessingPromise),
          );
        };
      };

      // Mark the prototype to prevent double-patching.
      proto.__OOBPublishErrorOtelPatched = true;
    }
  }
}
