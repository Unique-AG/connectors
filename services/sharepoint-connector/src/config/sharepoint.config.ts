import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { parseCommaSeparatedArray } from '../utils/config.util';
import { Redacted } from '../utils/redacted';

const oidcAuthModeConfig = z.object({
  authMode: z.literal('oidc').describe('Authentication mode to use for Microsoft APIs'),
});

const clientSecretAuthModeConfig = z.object({
  authMode: z.literal('client-secret').describe('Authentication mode to use for Microsoft APIs'),
  authClientId: z.string().nonempty().describe('Azure AD application client ID'),
  authClientSecret: z
    .string()
    .nonempty()
    .transform((val) => new Redacted(val))
    .describe('Azure AD application client secret for Microsoft APIs'),
});

const certificateAuthModeConfig = z
  .object({
    authMode: z.literal('certificate').describe('Authentication mode to use for Microsoft APIs'),
    authClientId: z.string().nonempty().describe('Azure AD application client ID'),
    authThumbprintSha1: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA1 thumbprint of the Azure AD application certificate'),
    authThumbprintSha256: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA256 thumbprint of the Azure AD application certificate'),
    authPrivateKeyPath: z
      .string()
      .nonempty()
      .describe(
        'Path to the private key file of the Azure AD application certificate in PEM format',
      ),
    authPrivateKeyPassword: z
      .string()
      .nonempty()
      .optional()
      .describe(
        'Password for the private key file of the Azure AD application certificate (if the key is encrypted)',
      ),
  })
  .refine((config) => config.authThumbprintSha1 || config.authThumbprintSha256, {
    message:
      'Either SHAREPOUNT_AUTH_THUMBPRINT_SHA1 or SHAREPOUNT_AUTH_THUMBPRINT_SHA256 has to be provided for certificate authentication mode',
  });

const baseConfig = z.object({
  authTenantId: z.string().min(1).describe('Azure AD tenant ID'),
  graphApiRateLimitPerMinute: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE)
    .describe('Number of MS Graph API requests allowed per minute'),
  baseUrl: z
    .url()
    .refine((url) => !url.endsWith('/'), {
      message: 'Base URL must not end with a trailing slash',
    })
    .describe("Your company's sharepoint URL"),
  siteIds: z
    .string()
    .transform(parseCommaSeparatedArray)
    .pipe(
      z.array(
        z.uuidv4({
          message: 'Each site ID must be a valid UUIDv4',
        }),
      ),
    )
    .describe('Comma-separated list of SharePoint site IDs to scan'),
  syncColumnName: z
    .string()
    .prefault('FinanceGPTKnowledge')
    .describe('Name of the SharePoint column indicating sync flag'),
});

export const SharepointConfigSchema = z
  .discriminatedUnion('authMode', [
    oidcAuthModeConfig,
    clientSecretAuthModeConfig,
    certificateAuthModeConfig,
  ])
  .and(baseConfig);

export const sharepointConfig = registerConfig('sharepoint', SharepointConfigSchema);

export type SharepointConfigNamespaced = NamespacedConfigType<typeof sharepointConfig>;
export type SharepointConfig = ConfigType<typeof sharepointConfig>;
