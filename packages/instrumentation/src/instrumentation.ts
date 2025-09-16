import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import {
  CompositePropagator,
  W3CBaggagePropagator,
  W3CTraceContextPropagator,
} from '@opentelemetry/core';
import { Instrumentation } from '@opentelemetry/instrumentation';
import { B3InjectEncoding, B3Propagator } from '@opentelemetry/propagator-b3';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { NodeSDK, NodeSDKConfiguration } from '@opentelemetry/sdk-node';
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions';
import { addCleanupListener } from 'async-cleanup';
import { type OtelConfig, parseOtelConfig } from './config.js';
import { createMetricReader } from './exporters/metrics.js';
import { createSpanProcessor } from './exporters/traces.js';

export interface InstrumentationOptions {
  defaultServiceName?: string;
  defaultServiceVersion?: string;
  includePgInstrumentation?: boolean;
  additionalInstrumentations?: Instrumentation[];
  configOverrides?: Partial<OtelConfig>;
}

/**
 * Initialize OpenTelemetry SDK with flexible configuration
 */
export function initOpenTelemetry(options: InstrumentationOptions = {}) {
  const {
    defaultServiceName = 'unknown-service',
    defaultServiceVersion = '0.0.0',
    includePgInstrumentation = false,
    additionalInstrumentations = [],
    configOverrides = {},
  } = options;

  const config = { ...parseOtelConfig(), ...configOverrides };

  console.log('OpenTelemetry Configuration:');
  console.log(
    `  Service: ${config.OTEL_SERVICE_NAME || defaultServiceName} v${config.OTEL_SERVICE_VERSION || defaultServiceVersion}`,
  );
  console.log(`  Traces Exporter: ${config.OTEL_TRACES_EXPORTER}`);
  console.log(`  Metrics Exporter: ${config.OTEL_METRICS_EXPORTER}`);

  // Create exporters based on configuration
  const metricReader = createMetricReader(config);
  const spanProcessor = createSpanProcessor(config);

  // Build instrumentations array
  const instrumentations = [
    getNodeAutoInstrumentations({
      '@opentelemetry/instrumentation-pino': {
        disableLogSending: process.env.NODE_ENV !== 'development', // Let infra pull from STDOUT in prod
      },
      '@opentelemetry/instrumentation-dns': { enabled: false },
      '@opentelemetry/instrumentation-net': { enabled: false },
      '@opentelemetry/instrumentation-fs': { enabled: false },
    }),
    ...additionalInstrumentations,
  ];

  // Add PG instrumentation if requested
  if (includePgInstrumentation) {
    try {
      const { PgInstrumentation } = require('@opentelemetry/instrumentation-pg');
      instrumentations.push(new PgInstrumentation());
    } catch (error) {
      console.warn(
        'PG instrumentation requested but @opentelemetry/instrumentation-pg not available:',
        error,
      );
    }
  }

  // Configure NodeSDK with optional exporters
  const sdkConfig: Partial<NodeSDKConfiguration> = {
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: config.OTEL_SERVICE_NAME || defaultServiceName,
      [ATTR_SERVICE_VERSION]: config.OTEL_SERVICE_VERSION || defaultServiceVersion,
    }),
    contextManager: new AsyncLocalStorageContextManager(),
    textMapPropagator: new CompositePropagator({
      propagators: [
        new W3CTraceContextPropagator(),
        new W3CBaggagePropagator(),
        new B3Propagator(),
        new B3Propagator({
          injectEncoding: B3InjectEncoding.MULTI_HEADER,
        }),
      ],
    }),
    instrumentations,
  };

  if (metricReader) sdkConfig.metricReader = metricReader;
  if (spanProcessor) sdkConfig.spanProcessor = spanProcessor;

  const otelSDK = new NodeSDK(sdkConfig);

  addCleanupListener(() => {
    otelSDK.shutdown().then(
      () => console.log('OpenTelemetry SDK shut down successfully'),
      (err) => console.log('Error shutting down OpenTelemetry SDK', err),
    );
  });

  otelSDK.start();
  console.log('OpenTelemetry SDK initialized successfully');

  return otelSDK;
}
