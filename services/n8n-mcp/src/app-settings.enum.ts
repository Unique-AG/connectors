import * as z from 'zod';

const appSettingsSchema = z.object({
  NODE_ENV: z.enum(['development', 'production']).prefault('development'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).prefault('info'),
  PORT: z
    .string()
    .transform((val) => parseInt(val, 10))
    .pipe(z.number().int().min(0).max(65535))
    .prefault('3000')
    .describe('The port that the MCP Server will listen on.'),
  DATABASE_URL: z
    .url()
    .startsWith('postgresql://')
    .describe('The prisma database url for Postgres. Must start with "postgresql://".'),
  ACCESS_TOKEN_EXPIRES_IN_SECONDS: z
    .string()
    .optional()
    .prefault('60')
    .transform((val) => parseInt(val, 10))
    .pipe(z.number().int())
    .describe('The expiration time of the access token in seconds. Default is 60 seconds.'),
  REFRESH_TOKEN_EXPIRES_IN_SECONDS: z
    .string()
    .optional()
    .prefault('2592000')
    .transform((val) => parseInt(val, 10))
    .pipe(z.number().int())
    .describe('The expiration time of the refresh token in seconds. Default is 30 days.'),
  ZITADEL_CLIENT_ID: z
    .string()
    .min(1)
    .describe('The client ID of the Zitadel App Registration that the MCP Server will use.'),
  ZITADEL_CLIENT_SECRET: z
    .string()
    .min(1)
    .describe('The client secret of the Zitadel App Registration that the MCP Server will use.'),
  ZITADEL_ISSUER: z
    .url()
    .describe('The issuer of the Zitadel App Registration that the MCP Server will use.'),
  ZITADEL_REQUIRED_ROLE: z
    .string()
    .optional()
    .describe('The required role that users must have in Zitadel to authenticate (optional).'),
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
      message:
        "Key must be 32 bytes (AES-256). Ensure its generated in a suitable way like 'openssl rand -hex 32' or terraform 'random_id'.",
    })
    .describe(
      'The secret key for the MCP Server to encrypt and decrypt data. Needs to be a 32-byte (256-bit) secret.',
    ),
  N8N_API_URL: z
    .url()
    .describe('The URL of your n8n instance (e.g., https://your-n8n.app.n8n.cloud).'),
  N8N_API_KEY: z.string().min(1).describe('The API key for authenticating with your n8n instance.'),
});

export const AppSettings = appSettingsSchema.keyof().enum;

export type AppConfig = z.infer<typeof appSettingsSchema>;

export function validateConfig(config: Record<string, unknown>): AppConfig {
  const parsed = appSettingsSchema.parse(config);
  return parsed;
}
