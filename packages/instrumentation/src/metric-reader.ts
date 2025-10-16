import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-proto';
import {
  ConsoleMetricExporter,
  MetricReader,
  PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics';
import { OtelConfig } from './config';

export function createMetricReader(config: OtelConfig): MetricReader | undefined {
  switch (config.OTEL_METRICS_READER) {
    case 'console':
      console.log('  Using console metrics reader');
      return new PeriodicExportingMetricReader({
        exporter: new ConsoleMetricExporter(),
      });
    case 'none':
      console.log('  Metrics reader disabled');
      return undefined;
    default:
      console.log('  Using default OTLP metrics reader');
      return new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter(),
      });
  }
}
