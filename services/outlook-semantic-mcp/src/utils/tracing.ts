import { trace } from '@opentelemetry/api';

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
