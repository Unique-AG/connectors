/**
 * This file MUST be imported before any other file in the application.
 * It monkey-patches the other imports to properly instrument the application.
 *
 * Don't include this file in the main.ts. Keep it as a separate file or JavaScript will hoist the imports and the instrumentation will not be applied.
 */
import { startInstrumentation } from '@unique-ag/instrumentation';
import { ExpressLayerType } from '@opentelemetry/instrumentation-express';

startInstrumentation({
  '@opentelemetry/instrumentation-amqplib': {
    useLinksForConsume: true,
  },
  '@opentelemetry/instrumentation-http': {
    ignoreIncomingRequestHook: (req) => {
      return (
        req.method === 'OPTIONS' || !!req.url?.includes('/probe') || !!req.url?.includes('/static')
      );
    },
  },
  '@opentelemetry/instrumentation-express': {
    ignoreLayersType: [ExpressLayerType.MIDDLEWARE, ExpressLayerType.ROUTER],
  },
});
