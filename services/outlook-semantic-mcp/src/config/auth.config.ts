import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';
import { offlineAccessSchema } from './features.config';

// Entra's shortest default Graph access-token lifetime. Without a refresh token the MCP session
// must end first, so the client signs the user in again instead of hitting an expired Graph token.
export const MAX_SESSION_WITHOUT_OFFLINE_ACCESS_SECONDS = 3600;

const ConfigSchema = z
  .object({
    accessTokenExpiresInSeconds: z.coerce
      .number<string | undefined>()
      .default(60)
      .describe('The expiration time of the access token in seconds. Default is 60 seconds.'),
    refreshTokenExpiresInSeconds: z.coerce
      .number<string | undefined>()
      .default(2592000)
      .describe('The expiration time of the refresh token in seconds. Default is 30 days.'),
    hmacSecret: redacted(z.string().min(1)).describe(
      'The secret key for the MCP Server to sign the OAuth session state and hash the stored MCP tokens. Rotating it signs out every user.',
    ),
    disableRateLimiting: z
      .stringbool()
      .default(false)
      .describe(
        'Emergency switch that skips the rate limit on every OAuth route. Leave off unless rate limiting itself is suspected in an incident.',
      ),
    microsoftOfflineAccess: offlineAccessSchema,
  })
  .transform(({ microsoftOfflineAccess, ...auth }, ctx) => {
    if (
      !microsoftOfflineAccess &&
      auth.refreshTokenExpiresInSeconds > MAX_SESSION_WITHOUT_OFFLINE_ACCESS_SECONDS
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['refreshTokenExpiresInSeconds'],
        input: auth.refreshTokenExpiresInSeconds,
        message: `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS must be at most ${MAX_SESSION_WITHOUT_OFFLINE_ACCESS_SECONDS} with MICROSOFT_OFFLINE_ACCESS=disabled, so the MCP session ends before the Microsoft access token does`,
      });
    }
    return {
      ...auth,
      refreshTokenExpiry: microsoftOfflineAccess ? ('sliding' as const) : ('absolute' as const),
    };
  });

export const authConfig = registerConfig('auth', ConfigSchema, {
  whitelistKeys: new Set(['MICROSOFT_OFFLINE_ACCESS']),
});

export type AuthConfigNamespaced = NamespacedConfigType<typeof authConfig>;
export type AuthConfig = ConfigType<typeof authConfig>;
