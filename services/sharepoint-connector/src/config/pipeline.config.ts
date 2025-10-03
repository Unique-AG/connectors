import {env} from 'node:process';
import {registerAs} from '@nestjs/config';
import {z} from 'zod';
import {
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_MS_GRAPH_RATE_LIMIT_PER_10_SECONDS,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';

const namespace = 'pipeline' as const;

const EnvironmentVariables = z.object({
  PROCESSING_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many files you want to ingest into unique at once'),
  STEP_TIMEOUT_SECONDS: z.coerce.number().int().positive().prefault(DEFAULT_STEP_TIMEOUT_SECONDS)
    .describe('Sets a time limit for a file processing step before it will stop and skip processing the file'),
  MAX_FILE_SIZE_BYTES: z.coerce.number().int().positive().prefault(DEFAULT_MAX_FILE_SIZE_BYTES)
    .describe('Sets the maximum file size in bytes that we are ingesting. Anything above this value will be skipped'),
  MS_GRAPH_RATE_LIMIT_PER_10_SECONDS: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_MS_GRAPH_RATE_LIMIT_PER_10_SECONDS)
    .describe('Number of MS Graph API requests allowed per 10 seconds'),
});

export interface PipelineConfig {
  [namespace]: {
    processingConcurrency: number;
    stepTimeoutSeconds: number;
    maxFileSizeBytes: number;
    msGraphRateLimitPer10Seconds: number;
  };
}

export const pipelineConfig = registerAs<PipelineConfig[typeof namespace]>(namespace, () => {
  const validEnv = EnvironmentVariables.safeParse(env);
  if (!validEnv.success) {
    throw new TypeError(`Invalid config for namespace "${ namespace }": ${ validEnv.error.message }`);
  }
  return {
    processingConcurrency: validEnv.data.PROCESSING_CONCURRENCY,
    stepTimeoutSeconds: validEnv.data.STEP_TIMEOUT_SECONDS,
    maxFileSizeBytes: validEnv.data.MAX_FILE_SIZE_BYTES,
    msGraphRateLimitPer10Seconds: validEnv.data.MS_GRAPH_RATE_LIMIT_PER_10_SECONDS,
  }
});
