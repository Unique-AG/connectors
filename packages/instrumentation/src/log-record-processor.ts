import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import {
  BatchLogRecordProcessor,
  ConsoleLogRecordExporter,
  LogRecordProcessor,
  SimpleLogRecordProcessor,
} from '@opentelemetry/sdk-logs';
import { OtelConfig } from './config';

export function createLogRecordProcessor(config: OtelConfig): LogRecordProcessor | undefined {
  switch (config.OTEL_LOGS_PROCESSOR) {
    case 'console':
      console.log('  Using console log record processor');
      return new SimpleLogRecordProcessor(new ConsoleLogRecordExporter());
    case 'otlp':
      console.log('  Using default OTLP log record processor');
      return new BatchLogRecordProcessor(new OTLPLogExporter());
    default:
      // By default we do not export logs, as we collect them directly via Kubernetes.
      console.log('  Log record processor disabled');
      return undefined;
  }
}
