import { z } from 'zod';

if (process.env.NODE_ENV !== 'production') {
  try {
    require('dotenv').config();
  } catch (_error) {
    console.debug('dotenv not available, skipping .env file loading');
  }
}

export const otelConfigSchema = z.object({
  OTEL_SPAN_PROCESSOR: z.enum(['otlp', 'langfuse', 'console', 'none']).prefault('otlp'),
  OTEL_METRICS_READER: z.enum(['otlp', 'console', 'none']).prefault('otlp'),

  // Langfuse configuration
  LANGFUSE_PUBLIC_KEY: z.string().optional(),
  LANGFUSE_SECRET_KEY: z.string().optional(),
  LANGFUSE_BASE_URL: z.url().optional(),
});

export type OtelConfig = z.infer<typeof otelConfigSchema>;

export function parseOtelConfig(): OtelConfig {
  return otelConfigSchema.parse(process.env);
}
