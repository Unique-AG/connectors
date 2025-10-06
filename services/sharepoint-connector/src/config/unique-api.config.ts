import { env } from 'node:process';
import { registerAs } from '@nestjs/config';
import { z } from 'zod';

const namespace = 'uniqueApi' as const;

const EnvironmentVariables = z.object({
  UNIQUE_SCOPE_ID: z
    .string()
    .optional()
    .describe(
      'Controls if you are using path based ingestion or scope based ingestion. Leave undefined for PATH based ingestion. Add your scope id for scope based ingestion.',
    ),
  UNIQUE_INGESTION_GRAPHQL_URL: z.url().describe('Unique graphql ingestion service URL'),
  UNIQUE_FILE_DIFF_URL: z.url().describe('Unique file diff service URL'),
  ZITADEL_OAUTH_TOKEN_URL: z.url().describe('Zitadel login token'),
  ZITADEL_PROJECT_ID: z.string().describe('Zitadel project ID'),
  ZITADEL_CLIENT_ID: z.string().describe('Zitadel client ID'),
  ZITADEL_CLIENT_SECRET: z.string().describe('Zitadel client secret'),
  UNIQUE_FILE_DIFF_BASE_PATH: z.string().prefault('https://next.qa.unique.app/'),
  SHAREPOINT_BASE_URL: z.url().describe("Your company's sharepoint URL"),
});

export interface UniqueApiConfig {
  [namespace]: {
    ingestionGraphQLUrl: string;
    fileDiffUrl: string;
    scopeId: string | undefined;
    zitadelOAuthTokenUrl: string;
    zitadelProjectId: string;
    zitadelClientId: string;
    zitadelClientSecret: string;
    fileDiffBasePath: string;
    sharepointBaseUrl?: string;
  };
}

export const uniqueApiConfig = registerAs<UniqueApiConfig[typeof namespace]>(namespace, () => {
  const validEnv = EnvironmentVariables.safeParse(env);
  if (!validEnv.success) {
    throw new TypeError(`Invalid config for namespace "${namespace}": ${validEnv.error.message}`);
  }

  return {
    ingestionGraphQLUrl: validEnv.data.UNIQUE_INGESTION_GRAPHQL_URL,
    fileDiffUrl: validEnv.data.UNIQUE_FILE_DIFF_URL,
    scopeId: validEnv.data.UNIQUE_SCOPE_ID ?? undefined,
    zitadelOAuthTokenUrl: validEnv.data.ZITADEL_OAUTH_TOKEN_URL,
    zitadelProjectId: validEnv.data.ZITADEL_PROJECT_ID,
    zitadelClientId: validEnv.data.ZITADEL_CLIENT_ID,
    zitadelClientSecret: validEnv.data.ZITADEL_CLIENT_SECRET,
    fileDiffBasePath: validEnv.data.UNIQUE_FILE_DIFF_BASE_PATH,
    sharepointBaseUrl: validEnv.data.SHAREPOINT_BASE_URL,
  };
});
