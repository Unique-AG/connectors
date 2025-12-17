import { LangfuseSpanProcessor } from '@langfuse/otel';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import {
  BatchSpanProcessor,
  ConsoleSpanExporter,
  SpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import { OtelConfig } from './config';

export function createSpanProcessor(config: OtelConfig): SpanProcessor | undefined {
  switch (config.OTEL_SPAN_PROCESSOR) {
    case 'langfuse':
      console.log('  Using langfuse span processor');
      return new LangfuseSpanProcessor({
        publicKey: config.LANGFUSE_PUBLIC_KEY,
        secretKey: config.LANGFUSE_SECRET_KEY,
        baseUrl: config.LANGFUSE_BASE_URL,
      });
    case 'console':
      console.log('  Using console span processor');
      return new BatchSpanProcessor(new ConsoleSpanExporter());
    case 'none':
      console.log('  Span processor disabled');
      return undefined;
    default:
      console.log('  Using default OTLP span processor');
      return new BatchSpanProcessor(new OTLPTraceExporter());
  }
}
