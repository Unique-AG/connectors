import * as z from 'zod';

if (process.env.NODE_ENV !== 'production') {
  try {
    require('dotenv').config();
  } catch (_error) {
    console.debug('dotenv not available, skipping .env file loading');
  }
}

export const TracesExporterType = z.enum(['otlp', 'langfuse', 'console', 'none']).prefault('otlp');
export const MetricsExporterType = z
  .enum(['otlp', 'prometheus', 'console', 'none'])
  .prefault('otlp');

export const otelConfigSchema = z.object({
  // Service identification
  OTEL_SERVICE_NAME: z.string().optional(),
  OTEL_SERVICE_VERSION: z.string().optional(),

  // Exporters configuration
  OTEL_TRACES_EXPORTER: TracesExporterType,
  OTEL_METRICS_EXPORTER: MetricsExporterType,

  // OTLP endpoints
  OTEL_EXPORTER_OTLP_ENDPOINT: z.url().optional(),
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: z.url().optional(),
  OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: z.url().optional(),

  // Prometheus configuration
  OTEL_EXPORTER_PROMETHEUS_HOST: z.string().optional().prefault('localhost'),
  OTEL_EXPORTER_PROMETHEUS_PORT: z.coerce.number().optional().prefault(8081),

  // Export intervals
  OTEL_METRIC_EXPORT_INTERVAL: z.coerce.number().optional().prefault(30000),
  OTEL_BSP_EXPORT_TIMEOUT: z.coerce.number().optional().prefault(30000),

  // Batch span processor configuration
  OTEL_BSP_SCHEDULE_DELAY: z.coerce.number().optional().prefault(5000),
  OTEL_BSP_MAX_EXPORT_BATCH_SIZE: z.coerce.number().optional().prefault(512),
  OTEL_BSP_MAX_QUEUE_SIZE: z.coerce.number().optional().prefault(2048),
});

export type OtelConfig = z.infer<typeof otelConfigSchema>;
export type TracesExporter = z.infer<typeof TracesExporterType>;
export type MetricsExporter = z.infer<typeof MetricsExporterType>;

export function parseOtelConfig(): OtelConfig {
  return otelConfigSchema.parse(process.env);
}
