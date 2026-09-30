import { z } from 'zod';

const booleanFromEnvironment = z.enum(['true', 'false']).transform((value) => value === 'true');

const url = z.url().transform((value) => new URL(value));

const configSchema = z
  .object({
    NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
    PORT: z.coerce.number().int().min(0).max(65_535).default(9560),
    AUTH_MODE: z.enum(['kong', 'development']).default('kong'),
    // `companyId:userId` used in development auth mode when a request carries no token.
    DEVELOPMENT_IDENTITY: z
      .string()
      .regex(/^[^:\s]+:[^:\s]+$/)
      .optional()
      .transform((value) => {
        const [companyId, userId] = value?.split(':') ?? [];
        return companyId && userId ? { companyId, userId } : undefined;
      }),
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
    CORS_ALLOWED_ORIGINS: z
      .string()
      .optional()
      .transform(
        (value) =>
          value
            ?.split(',')
            .map((origin) => origin.trim())
            .filter(Boolean) ?? [],
      )
      .pipe(
        z.array(
          z.url().transform((origin, context) => {
            const parsed = new URL(origin);
            if (
              parsed.username ||
              parsed.password ||
              parsed.pathname !== '/' ||
              parsed.search ||
              parsed.hash
            ) {
              context.addIssue({ code: 'custom', message: 'CORS origins must not contain a path' });
              return z.NEVER;
            }
            return parsed.origin;
          }),
        ),
      ),
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
    EGRESS_ALLOW_INSECURE: booleanFromEnvironment.prefault('false'),
    PUSH_NOTIFICATIONS_ENABLED: booleanFromEnvironment.prefault('false'),
    PUSH_ALLOWED_HOSTS: z
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
    ELICITATION_TIMEOUT_SECONDS: z.coerce.number().int().min(60).max(86_400).default(600),
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
    MAX_ACTIVE_EXECUTIONS_PER_TENANT: z.coerce.number().int().positive().default(50),
    MAX_ACTIVE_EXECUTIONS_PER_CONNECTION: z.coerce.number().int().positive().default(20),
    MAX_ACTIVE_TASKS_PER_TENANT: z.coerce.number().int().positive().default(50),
    MAX_REQUEST_BYTES: z.coerce
      .number()
      .int()
      .positive()
      .default(25 * 1024 * 1024),
    WORKER_ENABLED: booleanFromEnvironment.prefault('true'),
    WORKER_CONCURRENCY: z.coerce.number().int().positive().default(32),
    DEPENDENCY_TIMEOUT_MS: z.coerce.number().int().positive().default(2_000),
  })
  .superRefine((config, context) => {
    for (const key of ['PUBLIC_BASE_URL', 'ZITADEL_ISSUER'] as const) {
      const value = config[key];
      if (
        value.username ||
        value.password ||
        value.search ||
        value.hash ||
        (config.NODE_ENV === 'production' && value.protocol !== 'https:')
      ) {
        context.addIssue({
          code: 'custom',
          path: [key],
          message: 'public OAuth URLs must be clean HTTPS URLs in production',
        });
      }
    }
    if (config.PUSH_NOTIFICATIONS_ENABLED && !config.PUSH_ALLOWED_HOSTS.length) {
      context.addIssue({
        code: 'custom',
        path: ['PUSH_ALLOWED_HOSTS'],
        message: 'push notifications require approved webhook hosts',
      });
    }
    if (config.NODE_ENV === 'production' && config.EGRESS_ALLOW_INSECURE) {
      context.addIssue({
        code: 'custom',
        path: ['EGRESS_ALLOW_INSECURE'],
        message: 'insecure egress is forbidden in production',
      });
    }
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
    developmentIdentity:
      config.AUTH_MODE === 'development' ? config.DEVELOPMENT_IDENTITY : undefined,
    databaseUrl: config.DATABASE_URL,
    amqpUrl: config.AMQP_URL,
    publicBaseUrl: config.PUBLIC_BASE_URL,
    zitadelIssuer: config.ZITADEL_ISSUER,
    uniqueChatUrl: config.UNIQUE_CHAT_URL,
    uniqueScopeManagementUrl: config.UNIQUE_SCOPE_MANAGEMENT_URL,
    uniqueIngestionUrl: config.UNIQUE_INGESTION_URL,
    encryptionKey: config.ENCRYPTION_KEY,
    corsAllowedOrigins: config.CORS_ALLOWED_ORIGINS,
    egressAllowedHosts: config.EGRESS_ALLOWED_HOSTS,
    egressAllowInsecure: config.EGRESS_ALLOW_INSECURE,
    pushNotificationsEnabled: config.PUSH_NOTIFICATIONS_ENABLED,
    pushAllowedHosts: config.PUSH_ALLOWED_HOSTS,
    maxRemoteFileBytes: config.MAX_REMOTE_FILE_BYTES,
    elicitationTimeoutSeconds: config.ELICITATION_TIMEOUT_SECONDS,
    syncWaitMaxMs: config.SYNC_WAIT_MAX_MS,
    streamTimeoutMs: config.STREAM_TIMEOUT_MS,
    taskRetentionDays: config.TASK_RETENTION_DAYS,
    executionRetentionDays: config.EXECUTION_RETENTION_DAYS,
    pushMaxFailures: config.PUSH_MAX_FAILURES,
    reconcileIntervalSeconds: config.RECONCILE_INTERVAL,
    maxActiveExecutionsPerTenant: config.MAX_ACTIVE_EXECUTIONS_PER_TENANT,
    maxActiveExecutionsPerConnection: config.MAX_ACTIVE_EXECUTIONS_PER_CONNECTION,
    maxActiveTasksPerTenant: config.MAX_ACTIVE_TASKS_PER_TENANT,
    maxRequestBytes: config.MAX_REQUEST_BYTES,
    workerEnabled: config.WORKER_ENABLED,
    workerConcurrency: config.WORKER_CONCURRENCY,
    dependencyTimeoutMs: config.DEPENDENCY_TIMEOUT_MS,
  }));

export type GatewayConfig = z.infer<typeof configSchema>;
export const GATEWAY_CONFIG = Symbol('GATEWAY_CONFIG');

export function loadConfig(environment: NodeJS.ProcessEnv = process.env): GatewayConfig {
  return configSchema.parse(environment);
}
