import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { Redacted } from '../utils/redacted';

const UniqueConfig = z.object({
  scopeId: z
    .string()
    .optional()
    .describe(
      'Controls if you are using path based ingestion or scope based ingestion. Leave undefined for PATH based ingestion. Add your scope id for scope based ingestion.',
    ),
  ingestionGraphqlUrl: z.url().describe('Unique graphql ingestion service URL'),
  fileDiffUrl: z.url().describe('Unique file diff service URL'),
  zitadelOauthTokenUrl: z.url().describe('Zitadel login token'),
  zitadelProjectId: z.coerce.string().describe('Zitadel project ID'),
  zitadelClientId: z.coerce.string().describe('Zitadel client ID'),
  zitadelClientSecret: z.coerce
    .string()
    .transform((val) => new Redacted(val))
    .describe('Zitadel client secret'),
});

export const uniqueConfig = registerConfig('unique', UniqueConfig);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
