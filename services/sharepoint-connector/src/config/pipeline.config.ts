import { env } from 'node:process';
import { registerAs } from '@nestjs/config';
import { z } from 'zod';
import {
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';

const namespace = 'pipeline' as const;

export const EnvironmentVariables = z.object({
  PROCESSING_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .default(DEFAULT_PROCESSING_CONCURRENCY),
  STEP_TIMEOUT_SECONDS: z.coerce.number().int().positive().default(DEFAULT_STEP_TIMEOUT_SECONDS),
  MAX_FILE_SIZE_BYTES: z.coerce.number().int().positive().default(DEFAULT_MAX_FILE_SIZE_BYTES),
});

export interface Config {
  [namespace]: {
    processingConcurrency: number;
    stepTimeoutSeconds: number;
    maxFileSizeBytes: number;
  };
}

export const pipelineConfig = registerAs<Config[typeof namespace]>(namespace, () => {
  const validEnv = EnvironmentVariables.safeParse(env);
  if (!validEnv.success) {
    throw new TypeError(`Invalid config for namespace "${namespace}": ${validEnv.error.message}`);
  }
  return {
    processingConcurrency: validEnv.data.PROCESSING_CONCURRENCY,
    stepTimeoutSeconds: validEnv.data.STEP_TIMEOUT_SECONDS,
    maxFileSizeBytes: validEnv.data.MAX_FILE_SIZE_BYTES,
  } satisfies Config[typeof namespace];
});

export type PipelineConfig = typeof pipelineConfig;
