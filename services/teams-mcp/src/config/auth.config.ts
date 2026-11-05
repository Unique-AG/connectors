import { type ConfigType, type NamespacedConfigType } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';
import { registerConfig } from './register-config';

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
    'The secret key for the MCP Server to sign the OAuth session state and hash the stored MCP tokens. Rotating it signs out every user.',
  ),
});

export const authConfig = registerConfig('auth', ConfigSchema);

export type AuthConfigNamespaced = NamespacedConfigType<typeof authConfig>;
export type AuthConfig = ConfigType<typeof authConfig>;
