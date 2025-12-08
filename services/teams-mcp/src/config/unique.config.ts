import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted, stringToURL } from '~/utils/zod';

const ConfigSchema = z.object({
  apiBaseUrl: stringToURL().describe('The Public API URL.'),
  apiVersion: z
    .string()
    .default('2023-12-06')
    .describe('The Public API version to use (maps to `x-api-version`).'),
  appKey: redacted(z.string()).describe('API key of a Chat App (maps to `Authorization`).'),
  appId: z.string().describe('App ID of the Chat App (maps to `x-app-id`).'),
  authUserId: z.string().describe('User ID of a Zitadel Service User (maps to `x-user-id`).'),
  authCompanyId: z
    .string()
    .describe(
      'Organisation ID of where the Zitadel Service User is created (maps to `x-company-id`).',
    ),
  rootScopePath: z
    .string()
    .default('Teams-MCP')
    .describe('The root scope path where to upload recordings and transcripts.'),
});

export const uniqueConfig = registerConfig('unique', ConfigSchema);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
