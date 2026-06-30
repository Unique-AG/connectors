import { toAttributedError } from './classify-error';

/**
 * Method decorator for MCP tool handlers: any error thrown by the wrapped handler is
 * passed through {@link toAttributedError}, rewriting upstream Microsoft / network
 * failures into clearly-attributed messages while leaving `McpError` and unknown
 * errors untouched.
 *
 * Apply it ABOVE `@Span()` so the span still records the original (unattributed) error:
 *
 * ```ts
 * @Tool({ ... })
 * @AttributeUpstreamErrors()
 * @Span()
 * public async getChatMessages(...) { ... }
 * ```
 */
export function AttributeUpstreamErrors() {
  // biome-ignore lint/suspicious/noExplicitAny: types with decorators are simply not possible
  return (_target: any, _propertyKey: string, descriptor: PropertyDescriptor) => {
    const original = descriptor.value;

    descriptor.value = async function (this: unknown, ...args: unknown[]) {
      try {
        return await original.apply(this, args);
      } catch (error) {
        throw toAttributedError(error);
      }
    };

    // copy metadata from original to wrapped (to retain other decorators if any)
    Reflect.getMetadataKeys(original).forEach((key) => {
      const value = Reflect.getMetadata(key, original);
      Reflect.defineMetadata(key, value, descriptor.value);
    });

    return descriptor;
  };
}
