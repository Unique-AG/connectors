import { registerAs } from '@nestjs/config';
import { NamespacedConfigType } from '@proventuslabs/nestjs-zod';
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

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;

interface InheritanceSettings {
  inheritScopes: boolean;
  inheritFiles: boolean;
}

const INHERITANCE_MODES_MAP: Record<
  'inherit_scopes_and_files' | 'inherit_scopes' | 'inherit_files' | 'none',
  InheritanceSettings
> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
};