import * as z from 'zod';

const appSettingsSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).prefault('development'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).prefault('info'),
  PORT: z
    .string()
    .transform((val) => parseInt(val, 10))
    .pipe(z.int().min(0).max(65535))
    .prefault('3000')
    .describe('The port that the MCP Server will listen on.'),
  DATABASE_URL: z
    .url()
    .startsWith('postgresql://')
    .describe('The database url for Postgres. Must start with "postgresql://".'),
  AMQP_URL: z.url().describe('The URL of the RabbitMQ server. Must start with "amqp://".'),
  QDRANT_URL: z.url().describe('The URL of the Qdrant server. Must start with "http://".'),
  ACCESS_TOKEN_EXPIRES_IN_SECONDS: z
    .string()
    .optional()
    .prefault('60')
    .transform((val) => parseInt(val, 10))
    .pipe(z.int())
    .describe('The expiration time of the access token in seconds. Default is 60 seconds.'),
  REFRESH_TOKEN_EXPIRES_IN_SECONDS: z
    .string()
    .optional()
    .prefault('2592000')
    .transform((val) => parseInt(val, 10))
    .pipe(z.int())
    .describe('The expiration time of the refresh token in seconds. Default is 30 days.'),
  MICROSOFT_CLIENT_ID: z
    .string()
    .min(1)
    .describe('The client ID of the Microsoft App Registration that the MCP Server will use.'),
  MICROSOFT_CLIENT_SECRET: z
    .string()
    .min(1)
    .describe('The client secret of the Microsoft App Registration that the MCP Server will use.'),
  HMAC_SECRET: z.string().min(1).describe('The secret key for the MCP Server to sign HMAC tokens.'),
  SELF_URL: z.url().describe('The URL of the MCP Server. Used for oAuth callbacks.'),
  ENCRYPTION_KEY: z
    .union([z.string(), z.instanceof(Buffer)])
    .transform((key) => {
      if (Buffer.isBuffer(key)) {
        return key;
      }

      try {
        const hexBuffer = Buffer.from(key, 'hex');
        if (hexBuffer.length === key.length / 2) return hexBuffer;
      } catch {
        // fallback to base64
      }

      return Buffer.from(key, 'base64');
    })
    .refine((buffer) => buffer.length === 32, {
      error:
        "Key must be 32 bytes (AES-256). Ensure its generated in a suitable way like 'openssl rand -hex 32' or terraform 'random_id'.",
    })
    .describe(
      'The secret key for the MCP Server to encrypt and decrypt data. Needs to be a 32-byte (256-bit) secret.',
    ),
  JWT_PRIVATE_KEY: z
    .base64()
    .describe('The private key for the MCP Server to sign JWT tokens, base64 encoded.')
    .transform((val) => Buffer.from(val, 'base64').toString('utf-8')),
  JWT_PUBLIC_KEY: z
    .base64()
    .describe('The public key for the MCP Server to verify JWT tokens, base64 encoded.')
    .transform((val) => Buffer.from(val, 'base64').toString('utf-8')),
  JWT_KEY_ID: z.string().describe('The key ID for the MCP Server to sign JWT tokens.'),
  JWT_ALGORITHM: z
    .enum(['ES256', 'ES384', 'ES512'])
    .describe('The algorithm for the MCP Server to sign JWT tokens.'),
  PUBLIC_WEBHOOK_URL: z
    .url()
    .describe('The public webhook URL for the MCP Server to receive webhooks.'),
  MICROSOFT_WEBHOOK_SECRET: z
    .string()
    .describe('A random webhook secret to validate webhooks signed and sent by Microsoft.'),
  LITELLM_API_KEY: z.string().describe('The API key for Litellm.'),
  LITELLM_BASE_URL: z.url().describe('The base URL for Litellm.'),
  VOYAGE_API_KEY: z.string().describe('The API key for Voyage.'),
});

export const AppSettings = appSettingsSchema.keyof().enum;

export type AppConfig = z.infer<typeof appSettingsSchema>;

export function validateConfig(config: Record<string, unknown>): AppConfig {
  const parsed = appSettingsSchema.parse(config);
  return parsed;
}
