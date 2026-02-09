import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, OnApplicationBootstrap } from '@nestjs/common';
import { SpanStatusCode } from '@opentelemetry/api';
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

        // Listen once for a connection-level 'error' event.
        // Some AMQP errors may occur asynchronously (e.g., broker issues) and not
        // be thrown directly by the publish call; this captures those OOB errors.
        amqpConn.connection.once('error', onError);

        // Delegate to the original publish behavior with the original arguments.
        return original(...args).finally(() =>
          // Unregister the listener to prevent building them up over time.
          amqpConn.connection.removeListener('error', onError),
        );
      };

      // Swap the prototype method to our patched version so all subsequent
      // calls to amqpConn.publish go through our instrumentation.
      proto.publish = patched;

      // Mark the prototype to prevent double-patching.
      proto.__OOBPublishErrorOtelPatched = true;
    }
  }
}
