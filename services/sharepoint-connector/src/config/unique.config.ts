import { registerAs } from '@nestjs/config';
import { Redacted } from '../utils/redacted';
import { getTenantConfig } from './tenant-config-loader';
import { type UniqueConfig, UniqueConfigSchema } from './unique.schema';

export const uniqueConfig = registerAs('unique', (): UniqueConfig => {
  const config = UniqueConfigSchema.parse(getTenantConfig().unique);

  // Inject secrets from environment variables
  if (config.serviceAuthMode === 'external') {
    const secret = process.env.ZITADEL_CLIENT_SECRET;
    if (!secret) {
      throw new Error(
        'ZITADEL_CLIENT_SECRET environment variable is required when using external auth mode',
      );
    }
    return {
      ...config,
      zitadelClientSecret: new Redacted(secret),
    };
  }

  return config;
});

export type { UniqueConfig };
export type UniqueConfigNamespaced = { unique: UniqueConfig };
