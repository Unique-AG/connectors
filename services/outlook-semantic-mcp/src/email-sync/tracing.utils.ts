import type { Attributes } from '@opentelemetry/api';
import { SpanStatusCode, trace } from '@opentelemetry/api';

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
