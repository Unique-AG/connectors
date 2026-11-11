import { createLoggerOptions } from '@unique-ag/logger';
import { context, trace } from '@opentelemetry/api';
import type { Params } from 'nestjs-pino';
import { typeid } from 'typeid-js';
import type { AppConfig, TemenosConfig } from './config';
import { createRedactRequestSerializer } from './redact-request-serializer';

export function createAppLoggerOptions(app: AppConfig, temenos: TemenosConfig): Params {
  const loggerOptions = createLoggerOptions({
    secrets: [app.mcpApiKey.value, temenos.apiKey.value],
  });
  return {
    ...loggerOptions,
    pinoHttp: {
      ...loggerOptions.pinoHttp,
      level: app.logLevel,
      // The api-key lives in the URL path. The secret redaction skips values under 8 characters,
      // this serializer does not.
      serializers: {
        req: createRedactRequestSerializer(app.mcpApiKey.value),
      },
      mixin: () => {
        const span = trace.getActiveSpan();
        if (!span?.isRecording()) {
          return {};
        }
        const ctx = span.spanContext();
        return { trace_id: ctx.traceId, span_id: ctx.spanId, trace_flags: ctx.traceFlags };
      },
      genReqId: () => {
        const ctx = trace.getSpanContext(context.active());
        if (!ctx) {
          return typeid('trace').toString();
        }
        return ctx.traceId;
      },
    },
  };
}
