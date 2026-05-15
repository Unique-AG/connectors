export { AggregationType, InstrumentType, type ViewOptions } from '@opentelemetry/sdk-metrics';
export {
  type MetricsExporter,
  MetricsExporterType,
  type OtelConfig,
  otelConfigSchema,
  parseOtelConfig,
  type TracesExporter,
  TracesExporterType,
} from './config.js';
export { createMetricReader } from './exporters/metrics.js';
export { createSpanProcessor } from './exporters/traces.js';
export { type InstrumentationOptions, initOpenTelemetry } from './instrumentation.js';
export { runWithInstrumentation } from './utils.js';
