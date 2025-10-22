import { startObservation } from "@langfuse/tracing";
import { Attributes, Span, SpanContext } from "@opentelemetry/api";

/**
 * Langfuse does not support OTEL events, so we issue a separate Langfuse observation to track the event.
 */
export function addSpanEvent(
  span: Span,
  name: string,
  langfuseMetadata?: Record<string, unknown>,
  attributes?: Attributes,
  langfuseAttributes?: Record<string, unknown>
) {
  span.addEvent(name, attributes);

  startObservation(
    name,
    {
      ...(langfuseAttributes ?? {}),
      metadata: {
        ...(langfuseMetadata ?? {}),
        ...(attributes ?? {}),
      },
    },
    {
      asType: 'event',
      parentSpanContext: span.spanContext() as SpanContext,
    },
  ).end();
}
