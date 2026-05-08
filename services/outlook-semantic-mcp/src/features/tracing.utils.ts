import type { Attributes } from '@opentelemetry/api';
import { context, ROOT_CONTEXT, SpanStatusCode, trace } from '@opentelemetry/api';

export function traceAttrs(attrs: Attributes): void {
  const span = trace.getActiveSpan();
  if (span?.isRecording()) {
    span.setAttributes(attrs);
  }
}

export function traceEvent(name: string, attrs?: Attributes): void {
  const span = trace.getActiveSpan();
  if (span?.isRecording()) {
    span.addEvent(name, attrs);
  }
}

export function traceError(error: unknown): void {
  const span = trace.getActiveSpan();
  if (span?.isRecording()) {
    const exception = error instanceof Error ? error : String(error);
    span.recordException(exception);
    span.setStatus({
      code: SpanStatusCode.ERROR,
      message: exception.toString(),
    });
  }
}

function startNewTrace<T>(name: string, fn: () => Promise<T>): Promise<T> {
  const parentSpan = trace.getActiveSpan();
  const links = parentSpan ? [{ context: parentSpan.spanContext() }] : [];
  return context.with(ROOT_CONTEXT, () =>
    trace.getTracer('default').startActiveSpan(name, { links }, async (span) => {
      try {
        return await fn();
      } catch (err) {
        traceError(err);
        throw err;
      } finally {
        span.end();
      }
    }),
  );
}

/**
 * Starts a fresh root trace for each invocation, detached from any inherited async context.
 * Apply to cron job methods and AMQP listener handlers to prevent them from accumulating
 * spans under the long-lived startup trace.
 */
export function NewTrace(name: string): MethodDecorator {
  return (_target, _key, descriptor: PropertyDescriptor) => {
    const original = descriptor.value as (...args: unknown[]) => Promise<unknown>;
    descriptor.value = function (...args: unknown[]) {
      return startNewTrace(name, () => original.apply(this, args));
    };
    return descriptor;
  };
}
