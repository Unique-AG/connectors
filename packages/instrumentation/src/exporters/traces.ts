import { LangfuseSpanProcessor } from '@langfuse/otel';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import {
  BatchSpanProcessor,
  ConsoleSpanExporter,
  SpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import type { OtelConfig, TracesExporter } from '../config.js';

export function createSpanProcessor(config: OtelConfig): SpanProcessor | undefined {
  const exporterType: TracesExporter = config.OTEL_TRACES_EXPORTER;

  switch (exporterType) {
    case 'otlp': {
      const tracesEndpoint =
        config.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT ||
        (config.OTEL_EXPORTER_OTLP_ENDPOINT && `${config.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces`);

      if (!tracesEndpoint) {
        console.warn(
          'OTLP traces exporter requested but no endpoint configured. Skipping traces export.',
        );
        return undefined;
      }

      console.log(`  Traces Endpoint: ${tracesEndpoint}`);
      return new BatchSpanProcessor(
        new OTLPTraceExporter({
          url: tracesEndpoint,
        }),
        {
          exportTimeoutMillis: config.OTEL_BSP_EXPORT_TIMEOUT,
          scheduledDelayMillis: config.OTEL_BSP_SCHEDULE_DELAY,
          maxExportBatchSize: config.OTEL_BSP_MAX_EXPORT_BATCH_SIZE,
          maxQueueSize: config.OTEL_BSP_MAX_QUEUE_SIZE,
        },
      );
    }
    case 'langfuse':
      console.log('  Using langfuse traces exporter');
      return new LangfuseSpanProcessor();

    case 'console':
      console.log('  Using console traces exporter');
      return new BatchSpanProcessor(new ConsoleSpanExporter());

    case 'none':
      console.log('  Traces export disabled');
      return undefined;

    default:
      console.warn(`Unknown traces exporter: ${exporterType}. Falling back to OTLP.`);
      return createSpanProcessor({ ...config, OTEL_TRACES_EXPORTER: 'otlp' });
  }
}
