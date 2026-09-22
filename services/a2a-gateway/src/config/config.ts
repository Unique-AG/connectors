import { z } from 'zod';

const booleanFromEnvironment = z.enum(['true', 'false']).transform((value) => value === 'true');

const url = z.url().transform((value) => new URL(value));

const configSchema = z
  .object({
    NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
    PORT: z.coerce.number().int().min(0).max(65_535).default(9560),
    AUTH_MODE: z.enum(['kong', 'development']).default('kong'),
    DATABASE_URL: url.refine((value) => value.protocol === 'postgresql:', {
      message: 'DATABASE_URL must use postgresql:',
    }),
    AMQP_URL: url.refine((value) => ['amqp:', 'amqps:'].includes(value.protocol), {
      message: 'AMQP_URL must use amqp: or amqps:',
    }),
    PUBLIC_BASE_URL: url,
    ZITADEL_ISSUER: url,
    UNIQUE_CHAT_URL: url,
    UNIQUE_SCOPE_MANAGEMENT_URL: url,
    UNIQUE_INGESTION_URL: url,
    ENCRYPTION_KEY: z.string().regex(/^[a-fA-F0-9]{64}$/, 'ENCRYPTION_KEY must be 32-byte hex'),
    EGRESS_ALLOWED_HOSTS: z
      .string()
      .optional()
      .transform(
        (value) =>
          value
            ?.split(',')
            .map((host) => host.trim())
            .filter(Boolean) ?? [],
      ),
    MAX_REMOTE_FILE_BYTES: z.coerce
      .number()
      .int()
      .positive()
      .default(50 * 1024 * 1024),
    SYNC_WAIT_MAX_MS: z.coerce.number().int().positive().default(30_000),
    STREAM_TIMEOUT_MS: z.coerce
      .number()
      .int()
      .positive()
      .default(60 * 60 * 1000),
    TASK_RETENTION_DAYS: z.coerce.number().int().positive().default(30),
    EXECUTION_RETENTION_DAYS: z.coerce.number().int().positive().default(30),
    PUSH_MAX_FAILURES: z.coerce.number().int().positive().default(10),
    RECONCILE_INTERVAL: z.coerce.number().int().positive().default(300),
    WORKER_ENABLED: booleanFromEnvironment.prefault('true'),
    WORKER_CONCURRENCY: z.coerce.number().int().positive().default(4),
    DEPENDENCY_TIMEOUT_MS: z.coerce.number().int().positive().default(2_000),
  })
  .superRefine((config, context) => {
    if (config.NODE_ENV === 'production' && config.AUTH_MODE === 'development') {
      context.addIssue({
        code: 'custom',
        path: ['AUTH_MODE'],
        message: 'development authentication is forbidden in production',
      });
    }
  })
  .transform((config) => ({
    nodeEnv: config.NODE_ENV,
    port: config.PORT,
    authMode: config.AUTH_MODE,
    databaseUrl: config.DATABASE_URL,
    amqpUrl: config.AMQP_URL,
    publicBaseUrl: config.PUBLIC_BASE_URL,
    zitadelIssuer: config.ZITADEL_ISSUER,
    uniqueChatUrl: config.UNIQUE_CHAT_URL,
    uniqueScopeManagementUrl: config.UNIQUE_SCOPE_MANAGEMENT_URL,
    uniqueIngestionUrl: config.UNIQUE_INGESTION_URL,
    encryptionKey: config.ENCRYPTION_KEY,
    egressAllowedHosts: config.EGRESS_ALLOWED_HOSTS,
    maxRemoteFileBytes: config.MAX_REMOTE_FILE_BYTES,
    syncWaitMaxMs: config.SYNC_WAIT_MAX_MS,
    streamTimeoutMs: config.STREAM_TIMEOUT_MS,
    taskRetentionDays: config.TASK_RETENTION_DAYS,
    executionRetentionDays: config.EXECUTION_RETENTION_DAYS,
    pushMaxFailures: config.PUSH_MAX_FAILURES,
    reconcileIntervalSeconds: config.RECONCILE_INTERVAL,
    workerEnabled: config.WORKER_ENABLED,
    workerConcurrency: config.WORKER_CONCURRENCY,
    dependencyTimeoutMs: config.DEPENDENCY_TIMEOUT_MS,
  }));

export type GatewayConfig = z.infer<typeof configSchema>;
export const GATEWAY_CONFIG = Symbol('GATEWAY_CONFIG');

export function loadConfig(environment: NodeJS.ProcessEnv = process.env): GatewayConfig {
  return configSchema.parse(environment);
}
