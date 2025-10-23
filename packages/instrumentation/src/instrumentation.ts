import type { InstrumentationConfigMap } from '@opentelemetry/auto-instrumentations-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { addCleanupListener, exitAfterCleanup } from 'async-cleanup';
import { parseOtelConfig } from './config';
import { createLogRecordProcessor } from './log-record-processor';
import { createMetricReader } from './metric-reader';
import { createSpanProcessor } from './span-processor';

/**
 * Call this method as the very first before everything else.
 *
 * @param otelConfig Partial OTEL configuration for the `NodeSDK` instance
 */
export function startInstrumentation(nodeAutoInstrumentationsConfig?: InstrumentationConfigMap) {
  console.log('OpenTelemetry Configuration:');

  const config = parseOtelConfig();
  const spanProcessor = createSpanProcessor(config);
  const logRecordProcessor = createLogRecordProcessor(config);
  const metricReader = createMetricReader(config);

  const otelSDK = new NodeSDK({
    spanProcessors: spanProcessor ? [spanProcessor] : undefined,
    metricReader: metricReader,
    logRecordProcessors: logRecordProcessor ? [logRecordProcessor] : undefined,
    instrumentations: [getNodeAutoInstrumentations(nodeAutoInstrumentationsConfig)],
  });

  addCleanupListener(async () => {
    console.log('Shutting down OpenTelemetry SDK...');
    if (spanProcessor) {
      try {
        console.log('Flushing span processor...');
        await spanProcessor.forceFlush();
        console.log('Span processor flushed successfully');
      } catch (err) {
        console.error('Error flushing span processor:', err);
      }
    }

    await otelSDK
      .shutdown()
      .then(
        () => console.log('OpenTelemetry SDK shut down successfully'),
        (err) => console.log('Error shutting down OpenTelemetry SDK', err),
      )
      .finally(() => exitAfterCleanup(0));
  });

  otelSDK.start();
  console.log('OpenTelemetry SDK initialized successfully');
}
