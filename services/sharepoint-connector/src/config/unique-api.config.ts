import { env } from 'node:process';
import { registerAs } from '@nestjs/config';
import { z } from 'zod';

const namespace = 'uniqueApi' as const;

export const EnvironmentVariables = z.object({
  UNIQUE_INGESTION_URL_GRAPHQL: z.string().url(),
  UNIQUE_INGESTION_URL: z.string().url(),
  UNIQUE_SCOPE_ID: z.string().min(1).optional(),
  ZITADEL_OAUTH_TOKEN_URL: z.string().url(),
  ZITADEL_PROJECT_ID: z.string().min(1),
  ZITADEL_CLIENT_ID: z.string().min(1),
  ZITADEL_CLIENT_SECRET: z.string().min(1),
  UNIQUE_FILE_DIFF_BASE_PATH: z.string().min(1).default('https://next.qa.unique.app/'),
  UNIQUE_FILE_DIFF_PARTIAL_KEY: z.string().min(1).default('sharepoint/default'),
});

export interface Config {
  [namespace]: {
    ingestionGraphQLUrl: string;
    ingestionUrl: string;
    scopeId: string | undefined;
    zitadelOAuthTokenUrl: string;
    zitadelProjectId: string;
    zitadelClientId: string;
    zitadelClientSecret: string;
    fileDiffBasePath: string;
    fileDiffPartialKey: string;
  };
}

export const uniqueApiConfig = registerAs<Config[typeof namespace]>(namespace, () => {
  const validEnv = EnvironmentVariables.safeParse(env);
  if (!validEnv.success) {
    throw new TypeError(`Invalid config for namespace "${namespace}": ${validEnv.error.message}`);
  }
  return {
    ingestionGraphQLUrl: validEnv.data.UNIQUE_INGESTION_URL_GRAPHQL,
    ingestionUrl: validEnv.data.UNIQUE_INGESTION_URL,
    scopeId: validEnv.data.UNIQUE_SCOPE_ID,
    zitadelOAuthTokenUrl: validEnv.data.ZITADEL_OAUTH_TOKEN_URL,
    zitadelProjectId: validEnv.data.ZITADEL_PROJECT_ID,
    zitadelClientId: validEnv.data.ZITADEL_CLIENT_ID,
    zitadelClientSecret: validEnv.data.ZITADEL_CLIENT_SECRET,
    fileDiffBasePath: validEnv.data.UNIQUE_FILE_DIFF_BASE_PATH,
    fileDiffPartialKey: validEnv.data.UNIQUE_FILE_DIFF_PARTIAL_KEY,
  } satisfies Config[typeof namespace];
});

export type UniqueApiConfig = typeof uniqueApiConfig;
