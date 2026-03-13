import { ROOT_CONTEXT, SpanStatusCode, trace } from '@opentelemetry/api';

/**
 * Method decorator that starts a fresh root OpenTelemetry span, branching off an independent
 * trace for each invocation.
 *
 * Use on entry points that fire outside any HTTP request context — RabbitMQ subscribers,
 * cron jobs, etc. Without this, `trace.getActiveSpan()` falls back to the bootstrap span
 * and every invocation shares the same trace_id in logs.
 */
export function NewTrace(): MethodDecorator {
  return (target, propertyKey, descriptor: PropertyDescriptor) => {
    const original = descriptor.value;
    const spanName = `${target.constructor.name}.${String(propertyKey)}`;

    descriptor.value = function (...args: unknown[]) {
      return trace
        .getTracer('default')
        .startActiveSpan(spanName, {}, ROOT_CONTEXT, async (span) => {
          try {
            return await original.apply(this, args);
          } catch (error) {
            if (error instanceof Error) span.recordException(error);
            span.setStatus({ code: SpanStatusCode.ERROR });
            throw error;
          } finally {
            span.end();
          }
        });
    };

    Reflect.getMetadataKeys(original).forEach((key) => {
      const value = Reflect.getMetadata(key, original);
      Reflect.defineMetadata(key, value, descriptor.value);
    });

    return descriptor;
  };
}

/**
 * Updates the current span name to `class.method` if any.
 */
export function UpdateSpanName() {
  // biome-ignore lint/suspicious/noExplicitAny: types with decorators are simply not possible
  return (target: any, propertyKey: string, descriptor: PropertyDescriptor) => {
    const original = descriptor.value;

    // wrap the function call with added tracing calls
    descriptor.value = function (...args: unknown[]) {
      try {
        const className = this.constructor.name ?? target.constructor.name ?? 'UnknownClass';
        const span = trace.getActiveSpan(); // adapt to your tracer accessor
        span?.updateName(`${className}.${propertyKey}`);
      } catch {
        // swallow any tracing errors to avoid breaking business logic
      }
      return original.apply(this, args);
    };

    // copy metadata from original to wrapped (to retain other decorators if any)
    Reflect.getMetadataKeys(original).forEach((key) => {
      const value = Reflect.getMetadata(key, original);
      Reflect.defineMetadata(key, value, descriptor.value);
    });

    return descriptor;
  };
}
