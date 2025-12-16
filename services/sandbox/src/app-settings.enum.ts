import * as z from 'zod';

const appSettingsSchema = z.object({
  NODE_ENV: z.enum(['development', 'production']).prefault('development'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).prefault('info'),
  PORT: z
    .string()
    .transform((val) => parseInt(val, 10))
    .pipe(z.number().int().min(0).max(65535))
    .prefault('3067')
    .describe('The port that the server will listen on.'),
});

export const AppSettings = appSettingsSchema.keyof().enum;

export type AppConfig = z.infer<typeof appSettingsSchema>;

export function validateConfig(config: Record<string, unknown>): AppConfig {
  const parsed = appSettingsSchema.parse(config);
  return parsed;
}
