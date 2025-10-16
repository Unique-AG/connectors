import { Injectable } from '@nestjs/common';
import { Context, context, propagation, Span, SpanKind, SpanStatusCode, trace } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';

@Injectable()
export class TracePropagationService {
  public injectTraceContext(headers: Record<string, unknown> = {}): Record<string, unknown> {
    const carrier: Record<string, string> = {};
    propagation.inject(context.active(), carrier);
    return { ...headers, ...carrier };
  }

  public injectSpecificTraceHeaders(
    traceHeaders: Record<string, unknown>,
    additionalHeaders: Record<string, unknown> = {},
  ): Record<string, unknown> {
    return { ...additionalHeaders, ...traceHeaders };
  }

  public extractTraceContext(amqpMessage: ConsumeMessage): Context {
    const carrier = amqpMessage.properties.headers || {};
    return propagation.extract(context.active(), carrier);
  }

  public extractTraceHeaders(amqpMessage: ConsumeMessage): Record<string, unknown> {
    const headers = amqpMessage.properties.headers || {};
    const traceHeaders: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(headers)) {
      if (key.startsWith('traceparent') || key.startsWith('tracestate')) {
        traceHeaders[key] = value;
      }
    }
    return traceHeaders;
  }

  public startPipelineRootSpan(emailId: string, userProfileId: string): Span {
    const tracer = trace.getTracer('email-pipeline');
    return tracer.startSpan('email.pipeline', {
      kind: SpanKind.PRODUCER,
      root: true,
      attributes: {
        'pipeline.type': 'email',
        'email.id': emailId,
        'user.id': userProfileId,
        'langfuse.trace.metadata.emailId': emailId,
      },
    });
  }

  public withExtractedContext<T>(
    amqpMessage: ConsumeMessage,
    spanName: string,
    attributes: Record<string, string | number | boolean>,
    fn: (span: Span) => Promise<T>,
  ): Promise<T> {
    const extractedContext = this.extractTraceContext(amqpMessage);
    const tracer = trace.getTracer('email-pipeline');

    return context.with(extractedContext, async () => {
      const span = tracer.startSpan(spanName, {
        kind: SpanKind.CONSUMER,
        attributes: {
          ...attributes,
          'messaging.system': 'rabbitmq',
          'messaging.operation': 'process',
        },
      });

      return context.with(trace.setSpan(extractedContext, span), async () => {
        try {
          const result = await fn(span);
          return result;
        } catch (error) {
          span.setStatus({
            code: SpanStatusCode.ERROR,
            message: error instanceof Error ? error.message : String(error),
          });
          span.recordException(error as Error);
          throw error;
        } finally {
          span.end();
        }
      });
    });
  }
}

