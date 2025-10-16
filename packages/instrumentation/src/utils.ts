import { Link, Span, SpanStatusCode, trace } from '@opentelemetry/api';
import { addCleanupListener, exitAfterCleanup } from 'async-cleanup';

const createErrorHandler = (name: string, parentSpan: Span, error: unknown) => {
  const parentLink: Link = {
    context: parentSpan.spanContext(),
  };

  trace.getTracer('default').startActiveSpan(name, { root: true, links: [parentLink] }, (span) => {
    console.error(`[${name}] unhandled or uncaught error\n%o`, error);
    if (error instanceof Error) span.recordException(error);
    const message = error instanceof Error ? error.message : new String(error).toString();
    span.setStatus({
      code: SpanStatusCode.ERROR,
      message,
    });
    span.end();
  });
};

/**
 * Runs a function with OpenTelemetry instrumentation and error handling
 *
 * @param fn The function to execute
 * @param name The name for the root span
 * @returns Promise that resolves when the function completes
 */
export async function runWithInstrumentation(fn: () => Promise<void>, name = 'unknown') {
  console.log('Running with instrumentation', name);
  await trace.getTracer('default').startActiveSpan(name, { root: true }, async (span) => {
    const handler = (error: unknown) => createErrorHandler(name, span, error);
    process.addListener('unhandledRejection', handler);
    process.addListener('uncaughtException', handler);

    addCleanupListener(() => {
      process.removeListener('unhandledRejection', handler);
      process.removeListener('uncaughtException', handler);
    });

    let exitCode = 0;
    try {
      await fn();
      span.setStatus({
        code: SpanStatusCode.OK,
      });
    } catch (error) {
      console.error(`[${name}] execution error\n%o`, error);
      // biome-ignore lint/suspicious/noExplicitAny: We have a safe fallback for exitCode
      exitCode = (error as any)?.exitCode ?? 1;

      const message = error instanceof Error ? error.message : new String(error).toString();
      span.setStatus({
        code: SpanStatusCode.ERROR,
        message,
      });
      span.end();
      await exitAfterCleanup(exitCode);
    } finally {
      span.end();
    }
  });
}
