import type { Attributes, Context } from '@opentelemetry/api';
import type { IAttributesProcessor, ViewOptions } from '@opentelemetry/sdk-metrics';
import type { ReadableSpan, Span, SpanProcessor } from '@opentelemetry/sdk-trace';

const REDACTED = '[REDACTED]';

type Redact = (value: string) => string;

/** Redacts in `onEnding`, after routing has set `http.route` and the span name, while still writable. */
class RedactingSpanProcessor implements SpanProcessor {
  public constructor(private readonly redact: Redact) {}

  public onStart(_span: Span, _parentContext: Context): void {}

  public onEnding(span: Span): void {
    span.updateName(this.redact(span.name));
    for (const [key, value] of Object.entries(span.attributes)) {
      if (typeof value === 'string') {
        span.setAttribute(key, this.redact(value));
      }
    }
  }

  public onEnd(_span: ReadableSpan): void {}

  public forceFlush(): Promise<void> {
    return Promise.resolve();
  }

  public shutdown(): Promise<void> {
    return Promise.resolve();
  }
}

function redactAttributes(attributes: Attributes, redact: Redact): Attributes {
  return Object.fromEntries(
    Object.entries(attributes).map(([key, value]) => [
      key,
      typeof value === 'string' ? redact(value) : value,
    ]),
  );
}

export function createRedaction(sensitiveValues: string[]): {
  spanProcessor: SpanProcessor;
  httpMetricsView: ViewOptions;
} {
  const values = sensitiveValues.filter((value) => value.length > 0);
  const redact: Redact = (value) =>
    values.reduce((result, sensitive) => result.replaceAll(sensitive, REDACTED), value);
  const attributesProcessor: IAttributesProcessor = {
    process: (incoming) => redactAttributes(incoming, redact),
  };

  return {
    spanProcessor: new RedactingSpanProcessor(redact),
    // The HTTP server duration histogram carries `http.route`, which holds the raw route path.
    httpMetricsView: {
      meterName: '@opentelemetry/instrumentation-http',
      instrumentName: '*',
      attributesProcessors: [attributesProcessor],
    },
  };
}
