import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  accessTokenExpiresInSeconds: z.coerce
    .number()
    .default(60)
    .describe('The expiration time of the access token in seconds. Default is 60 seconds.'),
  refreshTokenExpiresInSeconds: z.coerce
    .number()
    .default(2592000)
    .describe('The expiration time of the refresh token in seconds. Default is 30 days.'),
  hmacSecret: redacted(z.string().min(1)).describe(
    'The secret key for the MCP Server to sign HMAC tokens.',
  ),
});

export const authConfig = registerConfig('auth', ConfigSchema);

export type AuthConfigNamespaced = NamespacedConfigType<typeof authConfig>;
export type AuthConfig = ConfigType<typeof authConfig>;
